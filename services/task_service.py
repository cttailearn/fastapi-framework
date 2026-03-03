"""任务业务逻辑层"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException, status

from repositories.task_repo import TaskRepository
from schemas.task import TaskCancelResponse, TaskResponse, TaskStatus, TaskSubmit


class TaskService:
    """任务服务层"""
    
    def __init__(self, repo: TaskRepository) -> None:
        self.repo = repo
        self._workers: dict[str, asyncio.Task[None]] = {}
    
    async def submit_task(
        self, task_submit: TaskSubmit, api_key_id: int | None, user_id: int | None
    ) -> TaskResponse:
        """提交新任务"""
        task_id = await self.repo.create(
            task_type=task_submit.type,
            data=task_submit.data,
            callback=task_submit.callback,
            config=task_submit.config,
            api_key_id=api_key_id,
            user_id=user_id,
        )
        
        task_data = await self.repo.get(task_id)
        if not task_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create task",
            )
        
        # 启动后台任务处理（模拟异步处理）
        worker = asyncio.create_task(self._process_task(task_id))
        self._workers[task_id] = worker
        
        return TaskResponse.model_validate(task_data)
    
    async def get_task(self, task_id: str) -> TaskResponse:
        """获取任务状态"""
        task_data = await self.repo.get(task_id)
        if not task_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )
        return TaskResponse.model_validate(task_data)
    
    async def cancel_task(self, task_id: str) -> TaskCancelResponse:
        """取消任务"""
        task_data = await self.repo.get(task_id)
        if not task_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )
        
        # 检查任务状态是否允许取消
        if task_data["status"] in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task {task_id} cannot be cancelled (status: {task_data['status']})",
            )
        
        success = await self.repo.cancel(task_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to cancel task",
            )
        
        # 取消后台 worker
        if task_id in self._workers:
            self._workers[task_id].cancel()
            del self._workers[task_id]
        
        updated_task = await self.repo.get(task_id)
        if not updated_task:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch updated task",
            )
        return TaskCancelResponse.model_validate(
            {
                "task_id": updated_task.get("task_id"),
                "status": updated_task.get("status"),
                "updated_at": updated_task.get("updated_at"),
            }
        )
    
    async def delete_task(self, task_id: str) -> None:
        """删除任务"""
        task_data = await self.repo.get(task_id)
        if not task_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )
        
        # 处理中的任务不允许删除
        if task_data["status"] == TaskStatus.PROCESSING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task {task_id} cannot be deleted while processing",
            )
        
        # 取消后台 worker
        if task_id in self._workers:
            self._workers[task_id].cancel()
            del self._workers[task_id]
        
        deleted = await self.repo.delete(task_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete task",
            )
    
    async def _process_task(self, task_id: str) -> None:
        """
        后台处理任务（模拟）
        
        实际项目中，这里应该：
        1. 从任务队列获取任务
        2. 根据 task type 调用相应的处理器
        3. 更新任务进度和状态
        4. 处理完成后更新结果或错误
        """
        try:
            # 更新状态为 processing
            await self.repo.update(task_id, status=TaskStatus.PROCESSING, progress=0)
            
            # 模拟处理过程（实际应该根据 task type 执行不同逻辑）
            task_data = await self.repo.get(task_id)
            if not task_data:
                return
            
            # 模拟进度更新
            for progress in [25, 50, 75, 100]:
                await asyncio.sleep(0.5)  # 模拟处理时间
                await self.repo.update(task_id, progress=progress)
            
            # 模拟处理结果
            result = {
                "message": f"Task {task_id} processed successfully",
                "type": task_data["type"],
            }
            
            await self.repo.update(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                completed_at=datetime.now(timezone.utc),
                result=result,
            )
            
        except asyncio.CancelledError:
            # 任务被取消
            await self.repo.update(task_id, status=TaskStatus.CANCELLED)
        except Exception as e:
            # 处理失败
            await self.repo.update(
                task_id,
                status=TaskStatus.FAILED,
                error={"code": 1001, "message": str(e)},
            )
