from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db
from ..scheduler import register_job_for_target, unregister_job

# 路由器前缀 /api/targets
router = APIRouter(prefix="/api/targets", tags=["targets"])


def _incident_to_out(incident) -> schemas.IncidentOut:
    """将故障事件 ORM 对象转换为响应模型。"""
    return schemas.IncidentOut(
        id=incident.id,
        target_id=incident.target_id,
        target_name=incident.target.name,
        started_at=incident.started_at,
        ended_at=incident.ended_at,
        duration_seconds=incident.duration_seconds,
    )


@router.get("", response_model=list[schemas.TargetOut])
def list_targets(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    查询所有监控目标。

    每个目标附带 uptime_percent（最近 50 条检测中在线占比，无记录为 None）。
    """
    targets = crud.get_targets(db, skip=skip, limit=limit)
    # 批量计算可用率，注入到响应中
    uptime_map = crud.compute_uptime_batch(db, [t.id for t in targets])
    result = []
    for t in targets:
        item = schemas.TargetOut.model_validate(t)
        item.uptime_percent = uptime_map.get(t.id)
        result.append(item)
    return result


@router.post("", response_model=schemas.TargetOut, status_code=status.HTTP_201_CREATED)
def add_target(data: schemas.TargetCreate, db: Session = Depends(get_db)):
    """
    新增监控目标。
    新增成功后若目标为启用状态，立即注册定时任务。
    """
    target = crud.create_target(db, data)
    # 定时任务注册：仅启用状态目标
    register_job_for_target(target)
    return target


@router.put("/{target_id}", response_model=schemas.TargetOut)
def modify_target(target_id: int, data: schemas.TargetUpdate, db: Session = Depends(get_db)):
    """修改监控目标，修改后同步更新定时任务。"""
    target = crud.get_target(db, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标不存在")

    target = crud.update_target(db, target, data)
    # 根据新状态刷新任务：启用则注册，停用或间隔变化则重建/移除
    if target.is_active:
        register_job_for_target(target)
    else:
        unregister_job(target.id)
    return target


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_target(target_id: int, db: Session = Depends(get_db)):
    """删除监控目标，同时移除其定时任务。"""
    target = crud.get_target(db, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标不存在")

    # 先从调度器移除任务，再删除数据库记录
    unregister_job(target.id)
    crud.delete_target(db, target)
    return None


@router.put("/{target_id}/toggle", response_model=schemas.TargetOut)
def toggle_target(target_id: int, db: Session = Depends(get_db)):
    """
    切换监控目标的启用/禁用状态。

    - 启用：注册该目标的定时任务
    - 禁用：移除定时任务（不删除历史数据）
    """
    target = crud.get_target(db, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标不存在")

    # 翻转启用状态并落库
    target.is_active = not target.is_active
    db.commit()
    db.refresh(target)

    # 同步调度器：启用则注册任务，禁用则移除任务
    if target.is_active:
        register_job_for_target(target)
    else:
        unregister_job(target.id)
    return target


@router.get("/{target_id}/incidents", response_model=list[schemas.IncidentOut])
def list_target_incidents(
    target_id: int, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)
):
    """
    查询单个目标的故障历史，按开始时间倒序。
    """
    target = crud.get_target(db, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标不存在")

    incidents = crud.get_incidents_for_target(db, target_id, skip=skip, limit=limit)
    return [_incident_to_out(inc) for inc in incidents]