from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Конфигурация БД (для старта используем SQLite, позже можно переключить на PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ecarsburg.db")

# Создаем движок
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

# Создаем фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс для всех моделей
Base = declarative_base()

# Функция для получения сессии (используется в роутах)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()