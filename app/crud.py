from sqlalchemy.orm import Session
from sqlalchemy import func

from . import models, schemas


def create_target(db: Session, data: schemas.TargetCreate) -> models.Target:
    """
    新增一个监控目标。

    schemas.TargetCreate 的 URL 已通过校验（http/https 开头）。
    """
    target = models.Target(
        name=data.name,
        url=data.url,
        interval_seconds=data.interval_seconds,
        expected_status=data.expected_status,
        timeout_seconds=data.timeout_seconds,
        is_active=data.is_active,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def get_target(db: Session, target_id: int) -> models.Target | None:
    """根据 id 查询单个目标，不存在时返回 None。"""
    return db.query(models.Target).filter(models.Target.id == target_id).first()


def get_targets(db: Session, skip: int = 0, limit: int = 100) -> list[models.Target]:
    """分页查询所有目标，默认按 id 升序。"""
    return (
        db.query(models.Target)
        .order_by(models.Target.id)
        .offset(skip)
        .limit(limit)
        .all()
    )


def update_target(
    db: Session, target: models.Target, data: schemas.TargetUpdate
) -> models.Target:
    """
    修改目标。仅更新 body 中显式传入（非 None）的字段，
    其余字段保持不变。
    """
    payload = data.model_dump(exclude_unset=True)

    # url 字段若传入，需校验格式（http/https 开头）
    if payload.get("url") is not None:
        schemas.TargetBase.validate_url(payload["url"])

    for field, value in payload.items():
        setattr(target, field, value)

    db.commit()
    db.refresh(target)
    return target


def delete_target(db: Session, target: models.Target) -> None:
    """删除目标及其关联的探测记录（级联删除）。"""
    db.delete(target)
    db.commit()


def create_check_record(
    db: Session,
    target_id: int,
    status_code: int | None,
    response_time_ms: float | None,
    is_up: bool,
    error_message: str | None,
    checked_at=None,
) -> models.CheckRecord:
    """新增一条探测记录。"""
    record = models.CheckRecord(
        target_id=target_id,
        status_code=status_code,
        response_time_ms=response_time_ms,
        is_up=is_up,
        error_message=error_message,
        checked_at=checked_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_checks_for_target(
    db: Session, target_id: int, skip: int = 0, limit: int = 50
) -> list[models.CheckRecord]:
    """查询某目标最近的探测记录，按时间倒序。"""
    return (
        db.query(models.CheckRecord)
        .filter(models.CheckRecord.target_id == target_id)
        .order_by(models.CheckRecord.checked_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def compute_uptime_batch(db: Session, target_ids: list[int]) -> dict[int, float | None]:
    """
    批量计算多个目标的可用率（uptime_percent）。

    规则：取每个目标最近 50 条检测记录，is_up=True 的占比 * 100，保留 1 位小数。
    无检测记录时返回 None。
    返回 {target_id: uptime_percent 或 None}。
    """
    result: dict[int, float | None] = {}
    if not target_ids:
        return result

    for tid in target_ids:
        recent = (
            db.query(models.CheckRecord)
            .filter(models.CheckRecord.target_id == tid)
            .order_by(models.CheckRecord.checked_at.desc())
            .limit(50)
            .all()
        )
        if not recent:
            result[tid] = None
            continue
        up_count = sum(1 for c in recent if c.is_up)
        result[tid] = round(up_count / len(recent) * 100, 1)
    return result


# ---------- 故障事件（incidents） ----------

def get_open_incident(db: Session, target_id: int) -> models.Incident | None:
    """
    查询某目标当前未结束的故障事件（ended_at IS NULL）。
    若存在返回该记录，否则返回 None。
    """
    return (
        db.query(models.Incident)
        .filter(models.Incident.target_id == target_id, models.Incident.ended_at.is_(None))
        .first()
    )


def create_incident(
    db: Session, target_id: int, started_at=None
) -> models.Incident:
    """新建一条故障事件（ended_at 默认为 null，表示故障进行中）。"""
    incident = models.Incident(target_id=target_id, started_at=started_at)
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def close_incident(db: Session, incident: models.Incident, ended_at=None) -> models.Incident:
    """
    结束一条故障事件：回填 ended_at，并计算持续秒数 duration_seconds。
    """
    incident.ended_at = ended_at
    if incident.started_at is not None and incident.ended_at is not None:
        incident.duration_seconds = int(
            (incident.ended_at - incident.started_at).total_seconds()
        )
    db.commit()
    db.refresh(incident)
    return incident


def update_incident_status(db: Session, target_id: int, is_up: bool) -> None:
    """
    根据本次探测结果维护故障事件（供定时任务与手动检测共用）：

    - 本次离线(is_up=False) 且当前无未结束故障 → 新建故障事件
    - 本次在线(is_up=True) 且存在未结束故障 → 回填结束时间与持续时长
    """
    open_incident = get_open_incident(db, target_id)
    if not is_up and open_incident is None:
        # 开始一段新故障
        create_incident(db, target_id)
    elif is_up and open_incident is not None:
        # 故障恢复
        close_incident(db, open_incident)


def get_incidents(db: Session, skip: int = 0, limit: int = 100) -> list[models.Incident]:
    """查询所有故障事件，按开始时间倒序。"""
    return (
        db.query(models.Incident)
        .order_by(models.Incident.started_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_incidents_for_target(
    db: Session, target_id: int, skip: int = 0, limit: int = 100
) -> list[models.Incident]:
    """查询单个目标的故障历史，按开始时间倒序。"""
    return (
        db.query(models.Incident)
        .filter(models.Incident.target_id == target_id)
        .order_by(models.Incident.started_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )