import string
import random
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pydantic import BaseModel

# DataBase

DATABASE_URL = "sqlite:///./shortener.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Мodel

class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, index=True)
    original_url = Column(String, nullable=False)
    short_code = Column(String(10), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    click_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)


# Создание таблиц
Base.metadata.create_all(bind=engine)

# Pydantic схемы

class LinkCreate(BaseModel):
    original_url: str
    custom_code: Optional[str] = None
    ttl_hours: Optional[int] = None


class LinkResponse(BaseModel):
    id: int
    original_url: str
    short_code: str
    short_url: str
    created_at: datetime
    expires_at: Optional[datetime]
    click_count: int
    is_active: bool

    class Config:
        from_attributes = True

# Бизнес-логика
def generate_code(length: int = 6) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


def create_link(db: Session, data: LinkCreate) -> Link:
    # Кастомный или случайный код
    if data.custom_code and data.custom_code.strip():
        code = data.custom_code.strip()
        if db.query(Link).filter(Link.short_code == code).first():
            raise ValueError(f"Код '{code}' уже занят")
    else:
        code = generate_code()
        while db.query(Link).filter(Link.short_code == code).first():
            code = generate_code()

    # TTL
    expires = None
    if data.ttl_hours and data.ttl_hours > 0:
        expires = datetime.utcnow() + timedelta(hours=data.ttl_hours)

    link = Link(original_url=data.original_url, short_code=code, expires_at=expires)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def is_expired(link: Link) -> bool:
    return bool(link.expires_at and link.expires_at < datetime.utcnow())