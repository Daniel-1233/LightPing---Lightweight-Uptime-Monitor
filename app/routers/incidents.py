from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db
from ..models import Incident

# 路由器前缀 /api/incidents
router = APIRouter(prefix="/api/incidents", tags=["incidents"])


def _to_out(incident: Incident) -> schemas.IncidentOut:
    """
    将 ORM 故障事件对象转换为响应模型（附带目标名称）。
    """
    return schemas.IncidentOut(
        id=incident.id,
        target_id=incident.target_id,
        target_name=incident.target.name,
        started_at=incident.started_at,
        ended_at=incident.ended_at,
        duration_seconds=incident.duration_seconds,
    )


@router.get("", response_model=list[schemas.IncidentOut])
def list_incidents(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    查询所有故障事件，按开始时间倒序，并附带目标名称。
    """
    incidents = crud.get_incidents(db, skip=skip, limit=limit)
    return [_to_out(inc) for inc in incidents]
