from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import models
from .database import Base, engine
from .routers import checks, incidents, targets
from .scheduler import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期管理：
    - 启动前创建数据库表
    - 启动定时调度器并注册既有目标的探测任务
    - 关闭时正常停止调度器
    """
    # 创建所有尚未存在的表
    Base.metadata.create_all(bind=engine)
    # 启动 APScheduler，为启用中的目标注册任务
    start_scheduler()
    yield
    # 关闭调度器
    shutdown_scheduler()


# 创建 FastAPI 应用，挂载生命周期
app = FastAPI(title="LightPing", version="0.1.0", lifespan=lifespan)

# 注册业务路由
app.include_router(targets.router)
app.include_router(checks.router)
app.include_router(incidents.router)

# 确定静态目录路径（static/index.html 占位页）
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/", include_in_schema=False)
def index():
    """返回静态占位页面。"""
    return FileResponse(STATIC_DIR / "index.html")


# 挂载静态资源目录（可选，便于后续前端资源引用）
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")