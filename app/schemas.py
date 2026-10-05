from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# 校验 URL 必须为 http/https 开头
HTTP_SCHEME_PREFIXES = ("http://", "https://")


class TargetBase(BaseModel):
    """
    目标基础模型：包含目标的核心字段，供新增与修改复用。
    校验 url 必须以 http/https 开头。
    """
    name: str = Field(..., min_length=1, max_length=255, description="目标名称")
    url: str = Field(..., description="监控 URL，必须以 http:// 或 https:// 开头")

    @classmethod
    def validate_url(cls, url: str) -> str:
        """
        校验 URL 格式：必须以 http:// 或 https:// 开头。
        若校验失败抛出 ValueError。
        """
        lowered = url.lower()
        if not lowered.startswith(HTTP_SCHEME_PREFIXES):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        if len(url.strip()) == 0:
            raise ValueError("URL 不能为空")
        return url


class TargetCreate(TargetBase):
    """新增目标时的请求体。"""
    interval_seconds: int = Field(60, gt=0, description="探测间隔（秒）")
    expected_status: int = Field(200, gt=0, lt=600, description="期望状态码")
    timeout_seconds: int = Field(10, gt=0, description="请求超时（秒）")
    is_active: bool = Field(True, description="是否启用")


class TargetUpdate(BaseModel):
    """修改目标时的请求体（所有字段可选）。"""
    name: str | None = Field(None, min_length=1, max_length=255)
    url: str | None = Field(None)
    interval_seconds: int | None = Field(None, gt=0)
    expected_status: int | None = Field(None, gt=0, lt=600)
    timeout_seconds: int | None = Field(None, gt=0)
    is_active: bool | None = None


class TargetOut(TargetBase):
    """目标的响应模型，包含 id 与创建时间。"""

    id: int
    interval_seconds: int
    expected_status: int
    timeout_seconds: int
    is_active: bool
    created_at: datetime
    # 可用率（最近 50 条检测中 is_up 占比）；无检测记录时为 null
    uptime_percent: float | None = None

    model_config = ConfigDict(from_attributes=True)


class CheckRecordOut(BaseModel):
    """探测记录的响应模型。"""

    id: int
    target_id: int
    status_code: int | None
    response_time_ms: float | None
    is_up: bool
    error_message: str | None
    checked_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncidentOut(BaseModel):
    """故障事件的响应模型（附带目标名称）。"""

    id: int
    target_id: int
    target_name: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None