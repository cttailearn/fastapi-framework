"""统一响应格式"""
from __future__ import annotations

from typing import Generic, Optional, TypeVar, Any

from pydantic import BaseModel, Field, ConfigDict

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""
    code: int = Field(0, description="业务状态码，0 表示成功")
    message: str = Field("success", description="状态描述")
    data: Optional[T] = Field(None, description="响应数据")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": 0,
                "message": "success",
                "data": {}
            }
        }
    )


def success_response(data: Optional[T] = None, code: int = 0, message: str = "success") -> APIResponse[T]:
    """成功响应"""
    return APIResponse[T](code=code, message=message, data=data)


def error_response(message: str, code: int = 1, data: Optional[Any] = None) -> APIResponse[Any]:
    """错误响应"""
    return APIResponse[Any](code=code, message=message, data=data)
