"""任务相关的 Pydantic 模型"""
from __future__ import annotations

from enum import Enum
from datetime import datetime
from typing import Optional, Any, Dict, Union

from pydantic import BaseModel, Field, ConfigDict


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"  # 排队中
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"  # 完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class TaskSubmit(BaseModel):
    """提交任务请求"""
    type: str = Field(..., description="任务类型，如 'text', 'image', 'video'")
    data: Optional[Union[str, Dict[str, Any]]] = Field(None, description="任务数据（文本内容或对象）")
    callback: Optional[str] = Field(None, description="回调 URL")
    config: Optional[Dict[str, Any]] = Field(None, description="任务配置参数")


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str = Field(..., description="任务唯一 ID")
    type: str = Field(..., description="任务类型")
    status: TaskStatus = Field(..., description="任务状态")
    progress: Optional[int] = Field(None, ge=0, le=100, description="进度百分比")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    result: Optional[Dict[str, Any]] = Field(None, description="任务结果")
    error: Optional[Dict[str, Any]] = Field(None, description="错误信息")
    estimated_remaining_seconds: Optional[int] = Field(None, description="预计剩余秒数")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                # 处理中状态
                {
                    "task_id": "tsk_1234567890",
                    "type": "text",
                    "status": "processing",
                    "progress": 45,
                    "created_at": "2025-03-15T10:00:00Z",
                    "updated_at": "2025-03-15T10:01:30Z",
                    "estimated_remaining_seconds": 120
                },
                # 完成状态
                {
                    "task_id": "tsk_1234567890",
                    "type": "text",
                    "status": "completed",
                    "progress": 100,
                    "created_at": "2025-03-15T10:00:00Z",
                    "updated_at": "2025-03-15T10:01:30Z",
                    "completed_at": "2025-03-15T10:01:30Z",
                    "result": {"sentiment": "positive", "keywords": ["示例", "文本"]}
                },
                # 失败状态
                {
                    "task_id": "tsk_1234567890",
                    "type": "image",
                    "status": "failed",
                    "progress": 30,
                    "created_at": "2025-03-15T10:00:00Z",
                    "updated_at": "2025-03-15T10:00:45Z",
                    "error": {"code": 2001, "message": "不支持的文件格式"}
                }
            ]
        }
    )


class TaskCancelResponse(BaseModel):
    """取消任务响应"""
    task_id: str = Field(..., description="任务 ID")
    status: TaskStatus = Field(..., description="任务状态")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "task_id": "tsk_1234567890",
                "status": "cancelled",
                "updated_at": "2025-03-15T10:02:00Z"
            }
        }
    )
