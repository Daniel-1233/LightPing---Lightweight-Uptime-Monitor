from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# SQLite 数据库文件路径
SQLALCHEMY_DATABASE_URL = "sqlite:///./lightping.db"

# 创建数据库引擎
# connect_args={"check_same_thread": False} 允许 FastAPI 多线程访问 SQLite
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """所有模型的基类"""
    pass


def get_db():
    """
    依赖注入：为每个请求提供一个独立的数据库会话。
    请求结束后自动关闭会话。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()