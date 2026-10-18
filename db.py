# База данных сайта «Соседи».
# Локально — файл sosedi.db (SQLite). На хостинге — PostgreSQL (Neon):
# адрес базы берём из переменной окружения DATABASE_URL.

import hashlib
import hmac
import os
import secrets
from datetime import datetime

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary,
                        String, Text, create_engine, inspect, select, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import data

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///sosedi.db")
# Neon даёт адрес вида postgresql://... — говорим SQLAlchemy использовать драйвер psycopg
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ===== Таблицы =====

class User(Base):
    __tablename__ = "users"
    login: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(200))
    premium_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # когда дал согласие на обработку данных
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Token(Base):
    """Сессии входа. Храним не сам токен, а его SHA-256:
    если базу украдут, по ней нельзя будет войти в чужой аккаунт"""
    __tablename__ = "tokens"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    login: Mapped[str] = mapped_column(ForeignKey("users.login", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner: Mapped[str | None] = mapped_column(ForeignKey("users.login", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(40))
    course: Mapped[int] = mapped_column(Integer)
    telegram: Mapped[str] = mapped_column(String(40))
    housing: Mapped[str] = mapped_column(String(20))
    budget: Mapped[str | None] = mapped_column(String(20), nullable=True)
    place: Mapped[str] = mapped_column(String(80), default="")
    when: Mapped[str] = mapped_column(String(40), default="")
    about: Mapped[str] = mapped_column(Text, default="")
    answers: Mapped[list] = mapped_column(JSON)
    gender: Mapped[str | None] = mapped_column(String(1), nullable=True)        # m / f
    seek_gender: Mapped[str | None] = mapped_column(String(3), nullable=True)   # m / f / any
    university: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    photo_version: Mapped[int] = mapped_column(Integer, default=0)  # 0 — фото нет
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Photo(Base):
    """Фото анкеты храним прямо в базе (на бесплатном хостинге файлы с диска пропадают)"""
    __tablename__ = "photos"
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    mime: Mapped[str] = mapped_column(String(30), default="image/jpeg")


class Interest(Base):
    __tablename__ = "interests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    to_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(20))
    from_login: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Payment(Base):
    """Оплаты подписки «Соседи+»: через ЮKassa или в демо-режиме"""
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(ForeignKey("users.login", ondelete="CASCADE"))
    plan: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="paid")   # pending / succeeded / canceled / paid (демо)
    demo: Mapped[bool] = mapped_column(Boolean, default=True)
    yk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # id платежа в ЮKassa
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ===== Пароли: храним не сам пароль, а его хеш =====

PBKDF2_ITERATIONS = 600_000  # столько рекомендует OWASP для PBKDF2-SHA256


def hash_password(password):
    """Формат: pbkdf2_sha256$итерации$соль$хеш"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def check_password(password, stored):
    """Сравнение за постоянное время (hmac.compare_digest), чтобы по скорости ответа нельзя было подбирать хеш.
    Понимает и старый формат «соль$хеш» со 100 000 итераций"""
    parts = stored.split("$")
    if len(parts) == 4:
        _, iterations, salt, digest = parts
        iterations = int(iterations)
    else:
        salt, digest = parts
        iterations = 100_000
    computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return hmac.compare_digest(computed, digest)


def needs_rehash(stored):
    """Старый хеш — пересчитаем при следующем входе"""
    return not stored.startswith(f"pbkdf2_sha256${PBKDF2_ITERATIONS}$")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


# ===== Создание таблиц и демо-данных =====

# новые столбцы, которых не было в первой версии базы: (таблица, столбец, тип)
NEW_COLUMNS = [
    ("profiles", "gender", "VARCHAR(1)"),
    ("profiles", "seek_gender", "VARCHAR(3)"),
    ("profiles", "university", "VARCHAR(80)"),
    ("profiles", "updated_at", "TIMESTAMP"),
    ("payments", "yk_id", "VARCHAR(64)"),
    ("users", "consent_at", "TIMESTAMP"),
]


def migrate():
    """Обновляем уже существующую базу без потери данных:
    добавляем новые столбцы и дописываем ответы на новые вопросы."""
    inspector = inspect(engine)
    existing = {(t, c["name"]) for t in ("profiles", "payments", "users") for c in inspector.get_columns(t)}
    with engine.begin() as conn:
        for table, column, sql_type in NEW_COLUMNS:
            if (table, column) not in existing:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}'))

    with SessionLocal() as s:
        changed = False
        for p in s.scalars(select(Profile)):
            demo = data.DEMO_EXTRA.get(p.name)
            is_demo = demo is not None and p.owner == demo["owner"]
            if len(p.answers) < data.N_QUESTIONS:
                if is_demo:
                    p.answers = list(demo["answers"])
                else:
                    # у старых анкет на новые вопросы ответа нет — None
                    p.answers = list(p.answers) + [None] * (data.N_QUESTIONS - len(p.answers))
                changed = True
            if is_demo and p.gender is None:
                p.gender, p.seek_gender, p.university = demo["gender"], demo["seek_gender"], demo["university"]
                changed = True
        if changed:
            s.commit()


def init_db():
    Base.metadata.create_all(engine)
    migrate()
    with SessionLocal() as s:
        if s.scalar(select(User).limit(1)) is not None:
            return  # база уже заполнена
        for u in data.DEMO_USERS:
            s.add(User(login=u["login"], name=u["name"], password_hash=hash_password(u["password"])))
        s.flush()
        ids = []
        for p in data.DEMO_PROFILES:
            profile = Profile(**p)
            s.add(profile)
            s.flush()
            ids.append(profile.id)
        for a, b in data.DEMO_INTERESTS:
            # демо-отметки «из прошлого», чтобы не съедали дневной лимит
            s.add(Interest(from_id=ids[a - 1], to_id=ids[b - 1], created_at=datetime(2026, 10, 10, 18, 20)))
        s.commit()
