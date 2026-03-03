# FastAPI 异步任务处理服务（带登录 / API-Key / 管理后台）

本项目实现了一个统一的异步任务处理 API（参考 [通用异步任务处理接口设计模板.md](file:///d:/tools/fastapi/api/通用异步任务处理接口设计模板.md)），并补齐：

- 用户注册/登录（Bearer Token）
- 登录后创建/吊销 API-Key
- 使用 API-Key 调用任务接口
- SQLite 持久化（默认 `db/app.sqlite3`）
- 管理后台 UI：登录后管理 API-Key、任务与请求日志

## 目录结构（核心）

```
api/
├── main.py                  # 应用入口：路由注册、DB初始化、请求日志中间件
├── core/
│   ├── config.py            # 配置与环境变量
│   ├── database.py          # SQLite 访问与建表
│   └── security.py          # 密码哈希/JWT/API-Key
├── deps/
│   └── auth.py              # 认证依赖：Bearer、API-Key、Admin Cookie
├── routes/
│   ├── auth_api.py          # /v1/auth/*
│   ├── api_keys.py          # /v1/api-keys/*
│   ├── tasks.py             # /v1/tasks/*
│   └── admin_ui.py          # /admin 后台
├── repositories/            # 数据访问层（SQLite）
├── schemas/                 # Pydantic 模型
├── services/                # 业务逻辑层
├── ui/                      # 管理后台模板（Jinja2）
└── tests/                   # 测试
```

## 快速开始

### 1) 安装依赖

```bash
uv run main.py
```

### 2) 启动服务

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

打开：

- OpenAPI：`http://localhost:8000/docs`
- 管理后台：`http://localhost:8000/admin/login`

## 环境变量

- `APP_DB_PATH`：SQLite 文件路径（默认 `db/app.sqlite3`）
- `APP_SECRET_KEY`：签名密钥（生产必须修改）
- `ACCESS_TOKEN_TTL_SECONDS`：Bearer Token 过期秒数（默认 24h）
- `ADMIN_COOKIE_NAME`：后台登录 Cookie 名称（默认 `admin_token`）
- `ADMIN_COOKIE_TTL_SECONDS`：后台 Cookie 过期秒数（默认 24h）

## 鉴权与调用方式

### 1) 注册 / 登录（Bearer Token）

首次注册的用户会自动成为管理员（便于初始化后台账号）。

```bash
curl -X POST http://localhost:8000/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password-123"}'

curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password-123"}'
```

登录成功后返回：

- `access_token`：用于调用需要登录态的接口（例如创建 API-Key）

### 2) 创建 API-Key（需要 Bearer）

```bash
curl -X POST http://localhost:8000/v1/api-keys \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"prod"}'
```

返回的 `api_key` 仅展示一次，请妥善保存。

### 3) 使用 API-Key 调用任务接口

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "X-API-Key: <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"type":"text","data":{"content":"hello"}}'
```

任务接口：

- `POST /v1/tasks`：提交任务
- `GET /v1/tasks/{task_id}`：查询任务
- `POST /v1/tasks/{task_id}/cancel`：取消任务
- `DELETE /v1/tasks/{task_id}`：删除任务

## 管理后台（UI）

- 地址：`/admin/login`
- 登录方式：管理员用户名/密码（后台登录态使用 HttpOnly Cookie）
- 功能：
  - 概览：用户、API-Key、任务、请求数量
  - API-Key：创建/吊销；新 Key 支持一键复制
  - 任务：查看最近任务；取消/删除
  - 请求：查看最近请求日志（含耗时、用户、API-Key 前缀）

## 测试与质量

```bash
pytest
ruff check .
mypy .
```

## 生产建议（必读）

- 必须设置强随机 `APP_SECRET_KEY`
- 建议通过反向代理提供 HTTPS（Cookie/SameSite 策略更可靠）
- SQLite 适合轻量单机；多实例/高并发建议替换为 Postgres 并引入连接池

