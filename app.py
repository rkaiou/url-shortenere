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

# FastApi

app = FastAPI(title="URL Shortener", version="1.0.0")
templates = Jinja2Templates(directory="templates")


# Web

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    links = db.query(Link).order_by(Link.created_at.desc()).all()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "links": links,
    })


@app.post("/shorten", response_class=HTMLResponse)
def shorten(
    request: Request,
    original_url: str = Form(...),
    custom_code: Optional[str] = Form(""),
    ttl_hours: Optional[str] = Form(""),
    db: Session = Depends(get_db),
):
    data = LinkCreate(
        original_url=original_url,
        custom_code=custom_code if custom_code and custom_code.strip() else None,
        ttl_hours=int(ttl_hours) if ttl_hours and ttl_hours.strip() else None,
    )

    error = None
    success = None

    try:
        link = create_link(db, data)
        success = f"{request.base_url}{link.short_code}"
    except ValueError as e:
        error = str(e)

    links = db.query(Link).order_by(Link.created_at.desc()).all()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "links": links,
        "success": success,
        "error": error,
    })


@app.get("/stats/{short_code}", response_class=HTMLResponse)
def stats_page(short_code: str, request: Request, db: Session = Depends(get_db)):
    link = db.query(Link).filter(Link.short_code == short_code).first()
    if not link:
        raise HTTPException(404, "Ссылка не найдена")
    return templates.TemplateResponse("stats.html", {
        "request": request,
        "link": link,
        "short_url": f"{request.base_url}{link.short_code}",
        "is_expired": is_expired(link),
    })


# Api

@app.post("/api/links", response_model=LinkResponse)
def api_create(data: LinkCreate, request: Request, db: Session = Depends(get_db)):
    try:
        link = create_link(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return LinkResponse(
        id=link.id,
        original_url=link.original_url,
        short_code=link.short_code,
        short_url=f"{request.base_url}{link.short_code}",
        created_at=link.created_at,
        expires_at=link.expires_at,
        click_count=link.click_count,
        is_active=link.is_active,
    )


@app.get("/api/links")
def api_list(db: Session = Depends(get_db)):
    return db.query(Link).order_by(Link.created_at.desc()).all()


@app.delete("/api/links/{short_code}")
def api_delete(short_code: str, db: Session = Depends(get_db)):
    link = db.query(Link).filter(Link.short_code == short_code).first()
    if not link:
        raise HTTPException(404, "Ссылка не найдена")
    db.delete(link)
    db.commit()
    return {"message": "Удалено"}

# Редирект
@app.get("/{short_code}")
def redirect(short_code: str, db: Session = Depends(get_db)):
    link = db.query(Link).filter(Link.short_code == short_code).first()

    if not link:
        raise HTTPException(404, "Ссылка не найдена")
    if is_expired(link):
        raise HTTPException(410, "Срок ссылки истёк")
    if not link.is_active:
        raise HTTPException(410, "Ссылка отключена")

    link.click_count += 1
    link.last_accessed = datetime.utcnow()
    db.commit()

    return RedirectResponse(url=link.original_url, status_code=307)


# Запуск

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=True)