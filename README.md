# FASTAPI.AI Backend

基于 FastAPI 的异步任务后端，提供：

- 用户注册/登录（Bearer Token）
- API-Key 管理与鉴权
- 异步任务提交、查询、取消、删除
- SQLite 持久化
- 管理后台静态页面挂载（`/admin`）
- DeepAgent 驱动的任务执行与工作区隔离

## 项目结构

```text
ai.lammps-backend/
├── main.py
├── core/
├── deps/
├── repositories/
├── routes/
├── schemas/
├── services/
├── db/
├── test/
├── ui/
├── pyproject.toml
└── README.md
```

## 架构说明

### 1) 启动与依赖注入

- `main.py` 在应用生命周期中初始化 SQLite 连接与数据表
- Repository 与 `TaskService` 挂载到 `app.state`
- 应用启动时自动恢复未完成任务（`pending/processing`）

### 2) 分层职责

- `routes/`：HTTP 接口层（参数解析、响应封装、鉴权依赖）
- `services/`：业务逻辑层（任务调度、执行、取消、文件处理）
- `repositories/`：数据访问层（SQLite CRUD）
- `schemas/`：请求/响应模型与状态定义
- `deps/`：认证与依赖注入

### 3) 任务执行模型

- `POST /v1/tasks` 创建任务后立即异步执行
- 每个任务有独立工作目录：`workspace/<task_id>/`
- 会把 `services/agents/skills` 复制到任务目录 `.skills/`
- 支持文件上传，文件保存到任务工作目录
- 任务默认走 deepagent runner；可用 `config.runner=dummy` 强制走 dummy

## DeepAgent（智能体服务）

本项目内置 DeepAgent 作为默认任务执行引擎，用于把“自然语言需求 → 可复现的工作区产物（脚本/文件/日志/报告）”串起来，并通过工具与 skills 扩展能力。

### 目录结构

```text
services/
└── agents/
    ├── agent.py          # 构建 DeepAgent：模型、工具、skills、backend
    ├── tools.py          # 提供可调用工具（如 exec_command）
    └── skills/           # skills 源目录（会复制到任务工作区 .skills/）
        └── skill-creator/
            ├── SKILL.md
            └── scripts/
```

### 运行条件

- 运行智能体任务（默认 runner=deepagent）需要环境变量：
  - `OPENAI_API_KEY`
  - `OPENAI_API_MODEL`
  - 可选：`OPENAI_API_BASE`
- 未配置 Key/Model 时，提交智能体任务会失败，并在任务 `error.message` 中返回缺失提示。
- 不想依赖模型时，可用 `type=dummy` 或 `config.runner=dummy` 做接口/链路自检。

### 工作区与隔离

- 每个任务在 `workspace/<task_id>/` 下创建独立工作目录，并将该目录作为智能体 backend root。
- 服务端会把该路径写入任务 `config.backend_root`，并在查询任务时返回：
  - `backend_root`：任务工作目录绝对路径（会被限制在 workspace 内）
  - `backend_files`：工作目录文件列表（默认最多 500 项、深度 5，跳过 `.skills` 与 `.deepagents`）
- DeepAgent 使用 `FilesystemBackend(virtual_mode=True)`，用于在任务目录内读写文件并与 tools/skills 协作。

### Skills 机制

- skills 源码位于 `services/agents/skills/`。
- 任务启动时，会把 skills 目录复制到任务工作目录下的 `/.skills/`，供 DeepAgent 以 “skills” 形式加载。
- Windows 下会自动跳过保留设备名目录（如 `con/prn/aux/nul/com1...`），避免复制失败。

### Runner 行为与 type 的关系

任务提交入口统一是 `POST /v1/tasks`，可同时使用：

- `type`：任务类型标签（必填）
- `config.runner`：执行器选择（可选，默认 deepagent）

当前内置 runner 行为：

- `deepagent`（默认）：调用 `services/agents/agent.py::build_agent()` 执行智能体推理与工具/skills 调用
- `dummy` / `echo`：内置模拟任务，返回输入回显并更新进度（用于接口联通自检）
- `command` / `exec`：以后台会话方式执行命令，并持续轮询进度与输出

当 `type` 为 `dummy/echo` 时，即使未显式设置 `config.runner` 也会自动走 dummy；其它任意 `type` 默认走 deepagent。

### 命令执行的安全限制（command/exec）

- 工作目录限制：命令执行的 `cwd` 必须位于 `workspace/` 下（允许在任务目录的父目录范围内切换），否则会被拒绝。
- 提权限制：若使用 `elevated=true` 相关能力，需要同时设置：
  - `DEEPAGENT_TOOLS_ELEVATED=1`
  - `DEEPAGENT_AGENT_ELEVATED=1`

## 快速开始

### 1) 安装依赖

```bash
uv sync
```

### 2) 启动服务

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：

- OpenAPI: `http://localhost:8000/docs`
- 管理后台: `http://localhost:8000/admin/`

## 环境变量

- `APP_DB_PATH`：数据库路径，默认 `db/app.sqlite3`
- `APP_SECRET_KEY`：JWT 签名密钥，生产环境必须替换
- `ACCESS_TOKEN_TTL_SECONDS`：访问令牌有效期，默认 86400 秒
- `OPENAI_API_KEY`：DeepAgent 使用的模型 Key（运行智能体任务必需）
- `OPENAI_API_MODEL`：DeepAgent 使用的模型名（运行智能体任务必需）
- `APP_AGENT_TIMEOUT_SECONDS`：智能体单次推理超时（秒），默认 300
- `APP_AGENT_HEARTBEAT_SECONDS`：智能体心跳更新间隔（秒），默认 15
- `APP_COMMAND_TIMEOUT_SECONDS`：命令任务最大运行时间（秒），默认 7200
- `APP_COMMAND_POLL_SECONDS`：命令任务轮询间隔（秒），默认 5
- `APP_COMMAND_IDLE_SECONDS`：命令任务无输出超时（秒），默认 1800

## 鉴权与接口

### 1) 注册与登录

```bash
curl -X POST http://localhost:8000/v1/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"password-123\"}"

curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"password-123\"}"
```

首次注册用户会被设置为管理员。

### 2) 创建 API-Key

```bash
curl -X POST http://localhost:8000/v1/api-keys \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"prod\"}"
```

### 3) 提交任务

任务提交统一使用 `POST /v1/tasks`，通过请求体中的 `type` 区分任务类型；并可通过 `config.runner` 控制具体执行器（runner）。

#### 请求字段

- `type`（必填）：任务类型字符串。当前内置的行为如下：
  - `agent`：智能体任务（默认走 DeepAgent）
  - `dummy` / `echo`：内置自检任务（不依赖模型 Key），返回输入回显并模拟进度
  - 其它任意字符串：作为业务侧分类标签保存，执行逻辑与 `agent` 一致（默认走 DeepAgent）
- `message`（可选）：单轮文本输入；也兼容字段名 `content`
- `messages`（可选）：多轮对话数组，元素为 `{ "role": "...", "content": "..." }`
  - 当 `messages` 与 `message` 同时传入时，会把 `message` 作为最后一条 `user` 消息追加
- `config`（可选）：任务配置对象（JSON）。常用字段：
  - `runner`：`deepagent`（默认）/ `dummy` / `echo` / `command` / `exec`
  - `thread_id` / `thread-id`：同一会话的线程 ID
  - `recursion_limit` / `recursion-limit`：递归/步数上限
  - `no_stream` / `no-stream`：是否关闭流式（后端会退回单次调用）

JSON 请求示例：

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "X-API-Key: <api_key>" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"agent\",\"message\":\"请生成一个LAMMPS输入脚本\"}"
```

dummy 自检任务示例（无需配置 `OPENAI_API_KEY` / `OPENAI_API_MODEL`）：

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "X-API-Key: <api_key>" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"dummy\",\"message\":\"hello\"}"
```

multipart/form-data（上传文件）示例（可多次传 `file`）：

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "X-API-Key: <api_key>" \
  -F "type=agent" \
  -F "message=请基于上传的结构文件生成 LAMMPS 输入脚本" \
  -F "file=@./example.pdb" \
  -F "config={\"thread_id\":\"demo\",\"recursion_limit\":512}"
```

command/exec runner 示例（仅建议在可信环境使用）：

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "X-API-Key: <api_key>" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"agent\",\"config\":{\"runner\":\"command\",\"command\":\"python -V\"}}"
```

接口列表：

- `POST /v1/tasks`：提交任务（支持 JSON / form-data）
- `GET /v1/tasks/{task_id}`：查询任务状态与结果
- `POST /v1/tasks/{task_id}/cancel`：取消任务
- `DELETE /v1/tasks/{task_id}`：删除任务

## 管理后台

- 地址：`/admin/#/login`
- 通过管理员账号登录
- 内部账号：admin，admin123
- 可查看概览、API-Key、任务和请求日志

## 测试与质量

```bash
uv run pytest
uv run ruff check .
uv run mypy .
```

## 生产建议

- 配置强随机 `APP_SECRET_KEY`
- 在反向代理层开启 HTTPS
- 高并发场景建议替换 SQLite 为 PostgreSQL
