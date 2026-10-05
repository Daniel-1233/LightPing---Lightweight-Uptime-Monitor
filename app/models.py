from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Float
from sqlalchemy.orm import relationship

from .database import Base


def utcnow() -> datetime:
    """返回带时区的当前 UTC 时间，供字段默认值使用。"""
    return datetime.now(timezone.utc)


class Target(Base):
    """
    监控目标表（targets）。

    记录被监控网站的地址、探测参数与启用状态。
    """
    __tablename__ = "targets"

    id = Column(Integer, primary_key=True, index=True)
    # 目标名称，例如 "官网首页"
    name = Column(String(255), nullable=False)
    # 目标 URL，必须以 http/https 开头
    url = Column(String(2048), nullable=False, index=True)
    # 探测间隔（秒），默认 60
    interval_seconds = Column(Integer, default=60, nullable=False)
    # 期望的 HTTP 状态码，用于判定 is_up，默认 200
    expected_status = Column(Integer, default=200, nullable=False)
    # 请求超时（秒），默认 10
    timeout_seconds = Column(Integer, default=10, nullable=False)
    # 是否启用监控，默认启用
    is_active = Column(Boolean, default=True, nullable=False)
    # 创建时间（UTC，带时区，前端可正确转换为本地时间）
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # 与探测记录的一对多关系
    checks = relationship("CheckRecord", back_populates="target", cascade="all, delete-orphan")
    # 与故障事件的一对多关系
    incidents = relationship("Incident", back_populates="target", cascade="all, delete-orphan")


class CheckRecord(Base):
    """
    探测记录表（check_records）。

    记录每次定时探测的结果，用于判断目标可用性。
    """
    __tablename__ = "check_records"

    id = Column(Integer, primary_key=True, index=True)
    # 外键关联到目标
    target_id = Column(Integer, ForeignKey("targets.id"), nullable=False, index=True)
    # 本次探测返回的 HTTP 状态码，超时/异常时为 None
    status_code = Column(Integer, nullable=True)
    # 响应耗时（毫秒）
    response_time_ms = Column(Float, nullable=True)
    # 是否在线（是否返回期望状态码）
    is_up = Column(Boolean, nullable=False)
    # 错误信息，正常时为 None
    error_message = Column(String(1024), nullable=True)
    # 探测时间（UTC，带时区，前端可正确转换为本地时间）
    checked_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # 反向关联目标
    target = relationship("Target", back_populates="checks")


class Incident(Base):
    """
    故障事件表（incidents）。

    记录目标从“离线”到“恢复”的完整故障时间段。
    ended_at 为 null 表示该故障仍在进行中。
    """
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    # 外键关联到目标
    target_id = Column(Integer, ForeignKey("targets.id"), nullable=False, index=True)
    # 故障开始时间（UTC，带时区）
    started_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    # 故障结束时间（UTC，带时区）；null 表示故障进行中
    ended_at = Column(DateTime(timezone=True), nullable=True)
    # 持续秒数；故障恢复后回填
    duration_seconds = Column(Integer, nullable=True)

    # 反向关联目标（用于序列化时附带目标名称）
    target = relationship("Target", back_populates="incidents")