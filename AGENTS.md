# AGENTS.md - 代码库指南

## 项目概述

本项目是一个 FastAPI 异步任务处理接口服务，参考设计文档见 `通用异步任务处理接口设计模板.md`。

---

## 1. 构建/测试/ lint 命令

### 初始化项目（首次设置）
```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install fastapi uvicorn pydantic python-multipart
pip install pytest pytest-asyncio httpx  # 测试
pip install ruff mypy  # 代码质量
```

### 推荐的项目配置（pyproject.toml）
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.mypy]
python_version = "3.10"
strict = true
```

### 运行命令
```bash
# 启动开发服务器
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 运行所有测试
pytest

# 运行单个测试文件
pytest tests/test_tasks.py

# 运行单个测试函数
pytest tests/test_tasks.py::test_submit_task

# 运行带标记的测试
pytest -m slow

# Lint 检查
ruff check .

# 自动格式化
ruff format .

# 类型检查
mypy .
```

---

## 2. 代码风格指南

### 导入规范
```python
# 顺序：标准库 → 第三方库 → 本地模块
# 每组之间空一行
import os
import json
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .schemas import TaskResponse
from .utils import generate_task_id
```

### 命名约定
| 类型 | 规范 | 示例 |
|------|------|------|
| 模块/文件 | snake_case | `task_service.py` |
| 类 | PascalCase | `TaskRepository` |
| 函数/变量 | snake_case | `get_task_by_id()` |
| 常量 | UPPER_SNAKE_CASE | `MAX_FILE_SIZE` |
| 私有成员 | 前缀 `_` | `_internal_cache` |

### 类型注解（必需）
```python
# ✅ 正确：完整的类型注解
def create_task(task_type: str, data: dict[str, Any]) -> Task:
    ...

# ❌ 错误：缺少类型注解
def create_task(task_type, data):
    ...
```

### 错误处理
```python
# 使用 FastAPI HTTPException
from fastapi import HTTPException, status

async def get_task(task_id: str) -> Task:
    task = await db.find_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    return task

# 自定义业务错误码（参考设计文档）
class BusinessException(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
```

### Pydantic 模型规范
```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Any

class TaskSubmit(BaseModel):
    type: str = Field(..., description="任务类型")
    data: Optional[dict[str, Any]] = None
    config: Optional[dict[str, Any]] = None

class TaskResponse(BaseModel):
    task_id: str
    type: str
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True
```

### 异步规范
```python
# 异步函数必须使用 await
async def process_task(task_id: str) -> Result:
    data = await fetch_data(task_id)  # ✅
    result = await compute(data)      # ✅
    return result

# 使用 asyncio.gather 并行执行
results = await asyncio.gather(
    fetch_user(user_id),
    fetch_permissions(user_id)
)
```

### 目录结构建议
```
api/
├── main.py              # FastAPI 应用入口
├── config.py            # 配置管理
├── schemas/             # Pydantic 模型
│   ├── task.py
│   └── response.py
├── routes/              # API 路由
│   └── tasks.py
├── services/            # 业务逻辑
│   └── task_service.py
├── repositories/        # 数据访问层
│   └── task_repo.py
├── utils/               # 工具函数
│   └── helpers.py
└── tests/               # 测试文件
    ├── test_tasks.py
    └── conftest.py
```

---

## 3. AI 代理规则

### 当前无 Cursor/Copilot 规则
本项目暂无 `.cursor/rules/`、`.cursorrules` 或 `.github/copilot-instructions.md` 文件。

### 代理行为准则
1. **类型安全优先**：禁止使用 `# type: ignore`、`cast(Any, ...)` 绕过类型检查
2. **测试驱动**：新增功能必须附带测试
3. **最小改动**：修复 bug 时只修改必要代码，不重构
4. **遵循设计文档**：API 接口严格遵循 `通用异步任务处理接口设计模板.md`
5. **错误码规范**：业务错误使用统一响应格式 `{"code": int, "message": str, "data": Any}`

### 提交前检查清单
- [ ] `ruff check .` 无错误
- [ ] `mypy .` 类型检查通过
- [ ] `pytest` 所有测试通过
- [ ] 新增代码有对应测试
- [ ] 遵循 API 设计文档规范
