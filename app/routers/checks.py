from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db
from ..scheduler import probe_target

# 路由器前缀 /api/targets/...
# 注意：此路由依赖目标存在，因此挂在 /api/targets 下
router = APIRouter(prefix="/api/targets", tags=["checks"])


@router.get("/{target_id}/checks", response_model=list[schemas.CheckRecordOut])
def list_checks(target_id: int, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """查询某个目标最近的探测记录。"""
    # 先确认目标存在
    target = crud.get_target(db, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标不存在")
    return crud.get_checks_for_target(db, target_id, skip=skip, limit=limit)


@router.post("/{target_id}/check-now", response_model=schemas.CheckRecordOut)
async def check_now(target_id: int, db: Session = Depends(get_db)):
    """
    手动触发一次可用性探测。

    流程：
    1. 校验目标是否存在（不存在返回 404）
    2. 复用 scheduler.probe_target 执行探测
    3. 将结果写入 check_records 表
    4. 返回本次探测结果
    """
    # 校验目标是否存在
    target = crud.get_target(db, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标不存在")

    # 复用统一的探测函数（与定时任务同一实现，不重复写探测逻辑）
    result = await probe_target(target)

    # 持久化本次手动探测结果
    record = crud.create_check_record(
        db,
        target_id=target.id,
        status_code=result["status_code"],
        response_time_ms=result["response_time_ms"],
        is_up=result["is_up"],
        error_message=result["error_message"],
    )

    # 依据本次结果维护故障事件（与定时任务共用同一逻辑）
    crud.update_incident_status(db, target.id, result["is_up"])

    return record