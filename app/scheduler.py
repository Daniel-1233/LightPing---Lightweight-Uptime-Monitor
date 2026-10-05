import logging
import time

import httpx
# 注意：探测函数是 async 协程，必须使用 AsyncIOScheduler（挂在事件循环上，
# 能够正确 await 协程）；BackgroundScheduler 使用线程池无法执行协程，任务会静默失效。
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import crud
from .database import SessionLocal
from .models import Target

logger = logging.getLogger(__name__)

# 全局调度器（基于 asyncio 事件循环，支持异步任务）
scheduler = AsyncIOScheduler()


async def probe_target(target: Target) -> dict:
    """
    对单个目标执行一次可用性探测（不落库，只返回结果）。

    返回字典：
    {
        "status_code": int | None,
        "response_time_ms": float | None,
        "is_up": bool,
        "error_message": str | None,
    }

    捕获全部网络/超时/未知异常，写入 error_message，保证不向上抛崩溃。
    该函数供定时任务与手动 check-now 接口复用。
    """
    # 记录请求开始时间（秒）
    start = time.monotonic()
    is_up = False
    status_code = None
    response_time_ms = None
    error_message = None

    try:
        # 使用异步 httpx 客户端发送 GET 请求
        timeout = httpx.Timeout(target.timeout_seconds, connect=target.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(target.url)

        # 计算响应耗时并转为毫秒
        response_time_ms = round((time.monotonic() - start) * 1000, 2)
        status_code = resp.status_code
        # 判定可用性：状态码是否等于期望值
        is_up = status_code == target.expected_status

    except httpx.TimeoutException as e:
        # 请求超时，不崩溃，记录错误信息
        error_message = f"请求超时: {e}"
    except httpx.HTTPError as e:
        # 网络/HTTP 层错误（DNS、拒绝连接等）
        error_message = f"HTTP 请求失败: {e}"
    except Exception as e:  # 兜底捕获，绝不崩溃
        error_message = f"探测异常: {e}"

    return {
        "status_code": status_code,
        "response_time_ms": response_time_ms,
        "is_up": is_up,
        "error_message": error_message,
    }


async def perform_check(target: Target) -> None:
    """
    对单个目标执行一次可用性探测，并写入数据库。
    复用 probe_target 完成实际请求，本函数只负责持久化。
    """
    # 定时任务运行于独立线程，SQLite 会话不能跨线程共享，
    # 因此这里新建一个会话，用完即关闭。
    db = SessionLocal()
    try:
        # 调用复用的探测函数
        result = await probe_target(target)

        # 持久化探测结果
        crud.create_check_record(
            db,
            target_id=target.id,
            status_code=result["status_code"],
            response_time_ms=result["response_time_ms"],
            is_up=result["is_up"],
            error_message=result["error_message"],
        )

        # 依据本次结果维护故障事件（离线开故障、在线恢复故障）
        crud.update_incident_status(db, target.id, result["is_up"])

        logger.info(
            "探测完成 target=%s is_up=%s status=%s time=%sms",
            target.name,
            result["is_up"],
            result["status_code"],
            result["response_time_ms"],
        )
    finally:
        db.close()


def register_job_for_target(target: Target) -> None:
    """
    为一个目标注册定时任务。
    只对 is_active=True 的目标执行。
    """
    if not target.is_active:
        return

    job_id = f"check_target_{target.id}"
    # 已存在的任务先移除，避免重复注册
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    # 按 interval_seconds 间隔，重复执行 perform_check
    scheduler.add_job(
        perform_check,
        trigger=IntervalTrigger(seconds=target.interval_seconds),
        id=job_id,
        replace_existing=True,
        args=[target],
        coalesce=True,      # 合并重叠的未执行任务，避免积压
        max_instances=1,    # 同一目标同时只允许一个任务运行
    )


def unregister_job(target_id: int) -> None:
    """根据目标 id 移除已注册的定时任务。"""
    job_id = f"check_target_{target_id}"
    job = scheduler.get_job(job_id)
    if job:
        scheduler.remove_job(job_id)


def start_scheduler() -> None:
    """
    启动调度器，并为数据库中所有启用目标注册任务。
    在 FastAPI 启动事件中调用。
    """
    if scheduler.running:
        return

    # 扫描所有 is_active=True 的目标
    db = SessionLocal()
    try:
        targets = crud.get_targets(db)
        for target in targets:
            if target.is_active:
                register_job_for_target(target)
    finally:
        db.close()

    # 启动后台调度器
    scheduler.start()


def shutdown_scheduler() -> None:
    """关闭调度器，在 FastAPI 关闭事件中调用。"""
    if scheduler.running:
        scheduler.shutdown(wait=False)