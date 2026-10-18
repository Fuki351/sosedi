# Сервер сайта «Соседи» на FastAPI
# Запуск: uvicorn main:app --reload --port 3000
# Данные хранятся в базе: локально SQLite (файл sosedi.db), на хостинге PostgreSQL (Neon)

import io
import os
import random
import re
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 40_000_000  # защита от «бомб» — крошечных файлов, которые распаковываются в гигантские картинки
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

import data
import yookassa
from db import (Interest, Payment, Photo, Profile, Report, SessionLocal, Token, User,
                check_password, hash_password, init_db, needs_rehash, token_hash)
from security import add_security_headers, rate_limit

app = FastAPI(title="Соседи — API", description="Сервер сайта для подбора соседа")
init_db()  # создаём таблицы и демо-данные, если база пустая


def get_db():
    """Сессия базы на время одного запроса"""
    with SessionLocal() as s:
        yield s


# ============ Шаг 1. Первый сервер ============

@app.get("/", response_class=PlainTextResponse)
def home():
    return "Привет, это сервер моего сайта «Соседи».\nСайт: /site/\nВсе запросы API: /docs"


@app.get("/time")
def get_time():
    now = datetime.now()
    return {"date": now.strftime("%d.%m.%Y"), "time": now.strftime("%H:%M:%S")}


@app.get("/random")
def get_random():
    return {"random": random.randint(1, 100)}


# ============ Вспомогательные функции ============

def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None


SESSION_DAYS = 30  # через 30 дней после входа нужно войти заново


def current_user(s, authorization):
    """Достаём пользователя по токену из заголовка Authorization: Bearer <токен>"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer "):].strip()
    if not token or len(token) > 128:
        return None
    row = s.get(Token, token_hash(token))
    if row is None:
        return None
    if row.created_at < datetime.now() - timedelta(days=SESSION_DAYS):
        s.delete(row)  # сессия устарела
        s.commit()
        return None
    return s.get(User, row.login)


def require_user(s, authorization):
    """То же самое, но если токена нет или он неверный — ошибка 401"""
    user = current_user(s, authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Нужно войти")
    return user


def profile_of(s, user):
    """Анкета пользователя (или None, если он её ещё не заполнил)"""
    if user is None:
        return None
    return s.scalar(select(Profile).where(Profile.owner == user.login))


def is_premium(user):
    return user is not None and user.premium_until is not None and user.premium_until > datetime.now()


def premium_owners(s):
    """Логины всех, у кого сейчас активна подписка"""
    return set(s.scalars(select(User.login).where(User.premium_until > datetime.now())))


def interests_left(s, user, my):
    """Сколько отметок «Интересно» осталось сегодня (None — без ограничений)"""
    if is_premium(user):
        return None
    if my is None:
        return data.FREE_DAILY_INTERESTS
    since = datetime.now() - timedelta(days=1)
    used = s.scalar(select(func.count()).select_from(Interest)
                    .where(Interest.from_id == my.id, Interest.created_at > since))
    return max(0, data.FREE_DAILY_INTERESTS - used)


def photo_url(p):
    if not p.photo_version:
        return None
    return f"/api/photos/{p.id}?v={p.photo_version}"


# ============ Шаг 5. Бизнес-логика: сервер считает сам ============

def compatibility(answers_a, answers_b):
    """Процент совместимости.
    Одинаковый ответ — 1 балл, соседний вариант — 0,5, противоположный — 0.
    Сумму делим на 9 и переводим в проценты."""
    score = 0
    count = 0
    for a, b in zip(answers_a, answers_b):
        if a is None or b is None:
            continue  # на этот вопрос кто-то ещё не ответил — не учитываем
        count += 1
        diff = abs(a - b)
        if diff == 0:
            score += 1
        elif diff == 1:
            score += 0.5
    if count == 0:
        return 0
    return round(score / count * 100)


def compare(answers_me, answers_other):
    """Таблица сравнения по каждому вопросу для карточки"""
    rows = []
    for i, question in enumerate(data.QUESTIONS):
        if i >= len(answers_me) or i >= len(answers_other):
            break
        if answers_me[i] is None or answers_other[i] is None:
            continue
        diff = abs(answers_me[i] - answers_other[i])
        result = "yes" if diff == 0 else ("part" if diff == 1 else "no")
        rows.append({
            "question": question,
            "me": data.ANSWERS[i][answers_me[i]],
            "other": data.ANSWERS[i][answers_other[i]],
            "result": result,
        })
    return rows


def make_tags(answers):
    """3 коротких метки для карточки — из ответов человека"""
    sleep = ["Ложится до 23:00", "Ложится до 01:00", "Ложится после 01:00"][answers[0]]
    smoke = "Курит" if answers[5] == 2 else "Не курит"
    if answers[6] == 0:
        third = "Есть питомец"
    else:
        third = ["Гости редко", "Гости иногда", "Гости часто"][answers[3]]
    return [sleep, smoke, third]


def has_interest(s, id_a, id_b):
    return s.scalar(select(Interest.id).where(Interest.from_id == id_a, Interest.to_id == id_b)) is not None


def is_mutual(s, id_a, id_b):
    """Интерес взаимный, если оба отметили друг друга"""
    return has_interest(s, id_a, id_b) and has_interest(s, id_b, id_a)


DEMO_LOGINS = {u["login"] for u in data.DEMO_USERS}


def short_card(p, my, premium_set):
    """Анкета для списка: без Telegram и без ответов"""
    if p.housing == "flat":
        housing_text = "Квартира · " + data.BUDGETS.get(p.budget, "")
    else:
        housing_text = data.HOUSING[p.housing]
    return {
        "id": p.id,
        "name": p.name,
        "course": p.course,
        "housing": p.housing,
        "housing_text": housing_text,
        "place": p.place,
        "tags": make_tags(p.answers),
        "university": p.university or "",
        "gender": p.gender,
        "photo": photo_url(p),
        "premium": p.owner in premium_set,
        # примеры анкет, которые сайт создаёт сам при первом запуске
        "demo": p.owner is None or p.owner in DEMO_LOGINS,
        "match": compatibility(my.answers, p.answers) if my is not None else None,
    }


# ============ Шаг 6. Вход и регистрация ============

def new_token(s, user):
    token = secrets.token_urlsafe(32)  # 256 бит случайности
    s.add(Token(token=token_hash(token), login=user.login))  # в базе — только хеш
    s.commit()
    return token


def forbid_demo(user):
    """Демо-аккаунты с паролями на странице входа — только посмотреть: менять и удалять анкету в них нельзя,
    иначе любой мог бы испортить пример"""
    if user.login in DEMO_LOGINS:
        raise HTTPException(status_code=403, detail="Это демо-аккаунт: менять его анкету нельзя. Зарегистрируйся, чтобы сделать свою")


WEAK_PASSWORDS = {"12345678", "123456789", "1234567890", "qwerty123", "password", "password1",
                  "11111111", "00000000", "qwertyuiop", "йцукенгш", "iloveyou", "abcd1234", "1q2w3e4r"}


class LoginIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=128)


@app.post("/api/login")
def login(body: LoginIn, request: Request, s=Depends(get_db)):
    rate_limit(request, "login", limit=10, per_seconds=300)                       # 10 попыток за 5 минут с адреса
    rate_limit(request, "login-user", limit=20, per_seconds=3600, key=body.login.strip().lower())  # и на один логин
    user = s.get(User, body.login.strip().lower())
    if user is None or not check_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)  # обновляем старый хеш до стойкого
    token = new_token(s, user)
    my = profile_of(s, user)
    return {"token": token, "name": user.name, "profile_id": my.id if my else None}


class RegisterIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=128)
    name: str = Field(max_length=80)
    consent: bool = False   # согласие на обработку персональных данных


@app.post("/api/register", status_code=201)
def register(body: RegisterIn, request: Request, s=Depends(get_db)):
    rate_limit(request, "register", limit=5, per_seconds=3600)  # не больше 5 аккаунтов в час с одного адреса
    if not body.consent:
        raise HTTPException(status_code=400, detail="Нужно согласие на обработку персональных данных")
    login_ = body.login.strip().lower()
    name = body.name.strip()
    if not re.fullmatch(r"[a-z0-9_]{3,20}", login_):
        raise HTTPException(status_code=400, detail="Логин: 3–20 символов, латиница, цифры и _")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Пароль — минимум 8 символов")
    if body.password.lower() in WEAK_PASSWORDS or body.password.lower() == login_:
        raise HTTPException(status_code=400, detail="Слишком простой пароль, придумай другой")
    if name == "" or len(name) > 40:
        raise HTTPException(status_code=400, detail="Имя должно быть от 1 до 40 символов")
    if s.get(User, login_) is not None:
        raise HTTPException(status_code=409, detail="Такой логин уже занят")
    user = User(login=login_, name=name, password_hash=hash_password(body.password), consent_at=datetime.now())
    s.add(user)
    s.commit()
    return {"token": new_token(s, user), "name": user.name, "profile_id": None}


@app.post("/api/logout")
def logout(authorization: str = Header(None), s=Depends(get_db)):
    """Выход: удаляем сессию на сервере, токен больше не действует"""
    if authorization and authorization.startswith("Bearer "):
        row = s.get(Token, token_hash(authorization[len("Bearer "):].strip()))
        if row is not None:
            s.delete(row)
            s.commit()
    return {"ok": True}


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=128)


@app.post("/api/me/delete")
def delete_account(body: DeleteAccountIn, request: Request, authorization: str = Header(None), s=Depends(get_db)):
    """Удалить аккаунт со всеми данными (право на отзыв согласия, 152-ФЗ). Нужен пароль"""
    rate_limit(request, "delete", limit=5, per_seconds=3600)
    user = require_user(s, authorization)
    forbid_demo(user)
    if not check_password(body.password, user.password_hash):
        raise HTTPException(status_code=403, detail="Неверный пароль")
    my = profile_of(s, user)
    if my is not None:
        s.execute(delete(Interest).where(or_(Interest.from_id == my.id, Interest.to_id == my.id)))
        s.execute(delete(Report).where(Report.profile_id == my.id))
        s.execute(delete(Photo).where(Photo.profile_id == my.id))
        s.delete(my)
    s.execute(delete(Token).where(Token.login == user.login))
    s.execute(delete(Payment).where(Payment.login == user.login))  # чеки остаются в ЮKassa и «Мой налог»
    s.delete(user)
    s.commit()
    return {"message": "Аккаунт и все данные удалены"}


@app.get("/api/me")
def me(authorization: str = Header(None), s=Depends(get_db)):
    user = require_user(s, authorization)
    my = profile_of(s, user)
    return {
        "login": user.login,
        "name": user.name,
        "profile_id": my.id if my else None,
        "seek_gender": my.seek_gender if my else None,
        "premium": is_premium(user),
        "premium_until": fmt(user.premium_until) if is_premium(user) else None,
        "interests_left": interests_left(s, user, my),
        # после обновления у старых анкет нет пола и ответов на новые вопросы
        "profile_incomplete": my is not None and (my.gender is None or None in my.answers),
    }


# ============ Шаг 3. REST API для анкет ============

BUDGET_ORDER = {"lt20": 0, "20to30": 1, "gt30": 2}


def has_answer(p, index, values):
    """У анкеты на вопрос index ответ из списка values"""
    return index < len(p.answers) and p.answers[index] in values


@app.get("/api/profiles")
def list_profiles(housing: str = "all", budget: str = "any",
                  no_smoke: bool = False, no_pets: bool = False,
                  gender: str = "any",        # кого ищу: m / f / any
                  course: str = "",           # курсы через запятую: "1,2"
                  university: str = "",       # часть названия вуза
                  place: str = "",            # часть названия метро или района
                  sleep: str = "any",         # lark — ложится до 23, owl — после 01
                  guests: str = "any",        # rare — гостей почти не зовёт
                  tidy: bool = False,         # убирается каждый день
                  quiet: bool = False,        # вечером нужна тишина или наушники
                  when: str = "any",          # now / month / later
                  with_photo: bool = False,
                  min_match: int = 0,         # совместимость не ниже, %
                  sort: str = "match",        # match / new / budget
                  authorization: str = Header(None), s=Depends(get_db)):
    user = current_user(s, authorization)
    my = profile_of(s, user)
    premium_set = premium_owners(s)

    query = select(Profile).order_by(Profile.id.desc())
    if my is not None:
        query = query.where(Profile.id != my.id)  # себя в списке не показываем
    if housing != "all":
        query = query.where(Profile.housing == housing)
    if budget != "any":
        query = query.where(Profile.budget == budget)
    if gender in ("m", "f"):
        query = query.where(Profile.gender == gender)
    courses = [int(c) for c in course.split(",") if c.strip().isdigit()]
    if courses:
        query = query.where(Profile.course.in_(courses))
    when_map = {"now": "Уже сейчас", "month": "В течение месяца", "later": "Позже"}
    if when in when_map:
        query = query.where(Profile.when == when_map[when])
    if with_photo:
        query = query.where(Profile.photo_version > 0)

    result = []
    for p in s.scalars(query):
        # поиск по тексту без учёта регистра: «рэу» найдёт «РЭУ им. Плеханова»
        if university.strip() and university.strip().lower() not in (p.university or "").lower():
            continue
        if place.strip() and place.strip().lower() not in (p.place or "").lower():
            continue
        if no_smoke and has_answer(p, 5, [2]):
            continue
        if no_pets and has_answer(p, 6, [0]):
            continue
        if sleep == "lark" and not has_answer(p, 0, [0]):
            continue
        if sleep == "owl" and not has_answer(p, 0, [2]):
            continue
        if guests == "rare" and not has_answer(p, 3, [0]):
            continue
        if tidy and not has_answer(p, 2, [0]):
            continue
        if quiet and not has_answer(p, 4, [0, 1]):
            continue
        # не показываем тех, кто ищет соседа другого пола, чем я
        if my is not None and my.gender and p.seek_gender in ("m", "f") and p.seek_gender != my.gender:
            continue
        card = short_card(p, my, premium_set)
        if min_match and card["match"] is not None and card["match"] < min_match:
            continue
        card["budget"] = p.budget
        result.append(card)

    # анкеты с «Соседи+» всегда выше, дальше — по выбранной сортировке
    if sort == "new":
        result.sort(key=lambda c: c["id"], reverse=True)
    elif sort == "budget":
        result.sort(key=lambda c: BUDGET_ORDER.get(c["budget"], 9))
    else:
        result.sort(key=lambda c: c["match"] or 0, reverse=True)
    result.sort(key=lambda c: c["premium"], reverse=True)  # сортировка устойчивая: порядок внутри сохранится
    return result


@app.get("/api/questions")
def questions():
    """Вопросы анкеты — по ним фронт сам строит форму"""
    return [{"section": q[0], "name": q[1], "text": q[2], "answers": q[3]} for q in data.QUESTION_LIST]


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: int, authorization: str = Header(None), s=Depends(get_db)):
    p = s.get(Profile, profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    user = current_user(s, authorization)
    my = profile_of(s, user)

    card = short_card(p, my, premium_owners(s))
    card["about"] = p.about
    card["when"] = p.when
    card["budget_text"] = data.BUDGETS.get(p.budget) if p.budget else None
    card["housing_name"] = data.HOUSING[p.housing]
    card["gender_text"] = data.GENDERS.get(p.gender)
    card["seek_text"] = data.SEEK_GENDERS.get(p.seek_gender)
    card["answers_text"] = [
        {"question": data.QUESTIONS[i], "answer": data.ANSWERS[i][a]}
        for i, a in enumerate(p.answers[:data.N_QUESTIONS]) if a is not None
    ]
    card["is_mine"] = my is not None and my.id == p.id
    card["telegram"] = None
    card["interest_sent"] = False
    card["mutual"] = False
    card["compare"] = None

    if my is not None and not card["is_mine"]:
        card["compare"] = compare(my.answers, p.answers)
        card["interest_sent"] = has_interest(s, my.id, p.id)
        card["mutual"] = is_mutual(s, my.id, p.id)
        if card["mutual"]:
            card["telegram"] = p.telegram  # контакт только при взаимном интересе

    if card["is_mine"]:
        card["telegram"] = p.telegram
        # своей анкете отдаём всё как есть — для формы редактирования
        card["edit"] = {
            "name": p.name, "course": p.course, "telegram": p.telegram, "about": p.about,
            "housing": p.housing, "budget": p.budget, "place": p.place, "when": p.when,
            "gender": p.gender, "seek_gender": p.seek_gender, "university": p.university or "",
            "answers": p.answers,
        }
    return card


class ProfileIn(BaseModel):
    name: str = Field(max_length=80)
    course: int
    telegram: str = Field(max_length=40)
    about: str = Field(default="", max_length=600)
    housing: str = Field(max_length=20)
    budget: str = Field(max_length=20)
    place: str = Field(default="", max_length=160)
    when: str = Field(default="", max_length=40)
    gender: str = Field(max_length=3)
    seek_gender: str = Field(max_length=3)
    university: str = Field(default="", max_length=160)
    answers: list[int] = Field(max_length=30)


def clean_profile(body):
    """Проверяем данные анкеты. Если что-то не так — ошибка 400, иначе — готовые поля"""
    name = body.name.strip()
    if name == "" or len(name) > 40:
        raise HTTPException(status_code=400, detail="Имя должно быть от 1 до 40 символов")
    if body.course < 1 or body.course > 6:
        raise HTTPException(status_code=400, detail="Курс — от 1 до 6")
    telegram = body.telegram.strip()
    if not telegram.startswith("@"):
        telegram = "@" + telegram
    if not re.fullmatch(r"@[A-Za-z0-9_]{5,32}", telegram):
        raise HTTPException(status_code=400, detail="Telegram: от 5 символов, латиница, цифры и _")
    if len(body.answers) != data.N_QUESTIONS or any(a not in (0, 1, 2) for a in body.answers):
        raise HTTPException(status_code=400, detail=f"Нужны ответы на все {data.N_QUESTIONS} вопросов")
    if body.housing not in data.HOUSING:
        raise HTTPException(status_code=400, detail="Неизвестный тип жилья")
    if body.budget not in data.BUDGETS:
        raise HTTPException(status_code=400, detail="Неизвестный бюджет")
    if body.gender not in data.GENDERS:
        raise HTTPException(status_code=400, detail="Укажи, парень ты или девушка")
    if body.seek_gender not in data.SEEK_GENDERS:
        raise HTTPException(status_code=400, detail="Укажи, кого ищешь в соседи")
    return {
        "name": name,
        "course": body.course,
        "telegram": telegram,
        "housing": body.housing,
        "budget": body.budget,
        "place": body.place.strip()[:80] or "Район не указан",
        "when": body.when if body.when in data.WHEN_OPTIONS else "",
        "about": body.about.strip()[:300],
        "gender": body.gender,
        "seek_gender": body.seek_gender,
        "university": body.university.strip()[:80],
        "answers": body.answers,
    }


@app.post("/api/profiles", status_code=201)
def create_profile(body: ProfileIn, request: Request, authorization: str = Header(None), s=Depends(get_db)):
    rate_limit(request, "profile", limit=10, per_seconds=3600)
    user = require_user(s, authorization)
    if profile_of(s, user) is not None:
        raise HTTPException(status_code=409, detail="У тебя уже есть анкета — её можно отредактировать")
    profile = Profile(owner=user.login, **clean_profile(body))
    s.add(profile)
    s.commit()
    return {"id": profile.id, "message": "Анкета опубликована"}


@app.put("/api/profiles/{profile_id}")
def update_profile(profile_id: int, body: ProfileIn, request: Request, authorization: str = Header(None), s=Depends(get_db)):
    """Редактирование своей анкеты: фото, отметки и подписка сохраняются"""
    rate_limit(request, "profile", limit=30, per_seconds=3600)
    user = require_user(s, authorization)
    forbid_demo(user)
    p = s.get(Profile, profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    if p.owner != user.login:
        raise HTTPException(status_code=403, detail="Редактировать можно только свою анкету")
    for field, value in clean_profile(body).items():
        setattr(p, field, value)
    p.updated_at = datetime.now()
    s.commit()
    return {"id": p.id, "message": "Изменения сохранены"}


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, authorization: str = Header(None), s=Depends(get_db)):
    user = require_user(s, authorization)
    forbid_demo(user)
    p = s.get(Profile, profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    if p.owner != user.login:
        raise HTTPException(status_code=403, detail="Удалить можно только свою анкету")

    # вместе с анкетой удаляем фото, отметки и жалобы, где она участвует
    s.execute(delete(Interest).where(or_(Interest.from_id == profile_id, Interest.to_id == profile_id)))
    s.execute(delete(Report).where(Report.profile_id == profile_id))
    s.execute(delete(Photo).where(Photo.profile_id == profile_id))
    s.delete(p)
    s.commit()
    return {"message": "Анкета удалена"}


# ============ Фото анкеты ============

MAX_PHOTO_BYTES = 8 * 1024 * 1024  # 8 МБ


@app.post("/api/profiles/{profile_id}/photo")
async def upload_photo(profile_id: int, request: Request, file: UploadFile = File(...),
                       authorization: str = Header(None), s=Depends(get_db)):
    rate_limit(request, "photo", limit=20, per_seconds=3600)
    user = require_user(s, authorization)
    forbid_demo(user)
    p = s.get(Profile, profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    if p.owner != user.login:
        raise HTTPException(status_code=403, detail="Фото можно менять только у своей анкеты")

    raw = await file.read(MAX_PHOTO_BYTES + 1)  # больше лимита даже не читаем
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Фото больше 8 МБ")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError("format")
        img = ImageOps.exif_transpose(img)  # чтобы фото с телефона не было повёрнуто
    except Exception:
        raise HTTPException(status_code=400, detail="Это не картинка. Подойдут JPG, PNG или WEBP")
    # дальше картинка рисуется заново и сохраняется без метаданных:
    # из фото пропадают EXIF с геолокацией, моделью телефона и датой съёмки

    # обрезаем по центру в квадрат 640×640 и сжимаем в JPEG
    img = ImageOps.fit(img.convert("RGB"), (640, 640), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82, optimize=True)

    photo = s.get(Photo, profile_id)
    if photo is None:
        s.add(Photo(profile_id=profile_id, data=out.getvalue(), mime="image/jpeg"))
    else:
        photo.data = out.getvalue()
    p.photo_version = (p.photo_version or 0) + 1
    s.commit()
    return {"photo": photo_url(p)}


@app.delete("/api/profiles/{profile_id}/photo")
def delete_photo(profile_id: int, authorization: str = Header(None), s=Depends(get_db)):
    user = require_user(s, authorization)
    forbid_demo(user)
    p = s.get(Profile, profile_id)
    if p is None or p.owner != user.login:
        raise HTTPException(status_code=403, detail="Фото можно менять только у своей анкеты")
    s.execute(delete(Photo).where(Photo.profile_id == profile_id))
    p.photo_version = 0
    s.commit()
    return {"photo": None}


@app.get("/api/photos/{profile_id}")
def get_photo(profile_id: int, s=Depends(get_db)):
    photo = s.get(Photo, profile_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Фото нет")
    # в адресе есть ?v=номер версии, поэтому браузер может долго хранить фото у себя
    return Response(photo.data, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000, immutable",
                             "Content-Disposition": "inline"})


# ============ Шаг 4. Вторая сущность: отметки «Интересно» ============

class InterestIn(BaseModel):
    to_id: int


@app.post("/api/interests", status_code=201)
def create_interest(body: InterestIn, request: Request, authorization: str = Header(None), s=Depends(get_db)):
    rate_limit(request, "interest", limit=60, per_seconds=600)
    user = require_user(s, authorization)
    my = profile_of(s, user)
    if my is None:
        raise HTTPException(status_code=400, detail="Сначала заполни свою анкету")
    other = s.get(Profile, body.to_id)
    if other is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    if other.id == my.id:
        raise HTTPException(status_code=400, detail="Нельзя отметить самого себя")

    if not has_interest(s, my.id, other.id):
        # без подписки — не больше 5 отметок в сутки
        if interests_left(s, user, my) == 0:
            raise HTTPException(status_code=402, detail="limit")
        s.add(Interest(from_id=my.id, to_id=other.id))  # дату сервер ставит сам
        s.commit()

    mutual = is_mutual(s, my.id, other.id)
    return {
        "mutual": mutual,
        "telegram": other.telegram if mutual else None,
        "interests_left": interests_left(s, user, my),
    }


@app.get("/api/interests")
def list_interests(authorization: str = Header(None), s=Depends(get_db)):
    """Отметки, где участвует текущий пользователь. Вместо id сервер подставляет имена (ручной аналог JOIN).
    Раньше список был открыт всем — это утечка: любой мог узнать, кто кого отметил"""
    user = require_user(s, authorization)
    my = profile_of(s, user)
    if my is None:
        return []
    result = []
    rows = s.scalars(select(Interest).where(or_(Interest.from_id == my.id, Interest.to_id == my.id)).order_by(Interest.id))
    for i in rows:
        a = s.get(Profile, i.from_id)
        b = s.get(Profile, i.to_id)
        result.append({
            "id": i.id,
            "from_id": i.from_id,
            "from_name": a.name if a else "—",
            "to_id": i.to_id,
            "to_name": b.name if b else "—",
            "created_at": fmt(i.created_at),
        })
    return result


@app.get("/api/interests/my")
def my_interests(authorization: str = Header(None), s=Depends(get_db)):
    """«Мои отметки»: кого отметил я, и кто отметил меня (список — только с «Соседи+»)"""
    user = require_user(s, authorization)
    my = profile_of(s, user)
    premium = is_premium(user)
    if my is None:
        return {"sent": [], "received_count": 0, "received": None, "premium": premium}

    sent = []
    for i in s.scalars(select(Interest).where(Interest.from_id == my.id).order_by(Interest.id.desc())):
        other = s.get(Profile, i.to_id)
        if other is None:
            continue
        mutual = is_mutual(s, my.id, other.id)
        sent.append({
            "profile_id": other.id,
            "name": other.name,
            "photo": photo_url(other),
            "match": compatibility(my.answers, other.answers),
            "mutual": mutual,
            "telegram": other.telegram if mutual else None,
            "created_at": fmt(i.created_at),
        })

    received_rows = list(s.scalars(select(Interest).where(Interest.to_id == my.id).order_by(Interest.id.desc())))
    received = None
    if premium:
        received = []
        for i in received_rows:
            other = s.get(Profile, i.from_id)
            if other is None:
                continue
            received.append({
                "profile_id": other.id,
                "name": other.name,
                "photo": photo_url(other),
                "match": compatibility(my.answers, other.answers),
                "mutual": has_interest(s, my.id, other.id),
                "created_at": fmt(i.created_at),
            })
    return {"sent": sent, "received_count": len(received_rows), "received": received, "premium": premium}


# ============ Монетизация: подписка «Соседи+» ============
# Если в окружении есть ключи ЮKassa — настоящая оплата (в тестовом магазине — тестовыми картами).
# Если ключей нет — демо-режим: подписка включается сразу, деньги не списываются.

def activate_payment(s, payment):
    """Включаем подписку за оплаченный платёж. Повторный вызов ничего не сделает"""
    if payment.status == "succeeded":
        return
    plan = data.PLANS[payment.plan]
    user = s.get(User, payment.login)
    start = user.premium_until if is_premium(user) else datetime.now()
    user.premium_until = start + timedelta(days=plan["days"])  # продлеваем, если уже есть
    payment.status = "succeeded"
    s.commit()


def sync_payment(s, payment):
    """Спрашиваем у ЮKassa статус платежа и обновляем его у себя"""
    if payment.yk_id is None or payment.status in ("succeeded", "canceled"):
        return payment.status
    info = yookassa.get_payment(payment.yk_id)
    if info["status"] == "succeeded":
        activate_payment(s, payment)
    elif info["status"] == "canceled":
        payment.status = "canceled"
        s.commit()
    return payment.status


def site_origin(request):
    """Адрес сайта, на который ЮKassa вернёт человека после оплаты.
    Берём из настройки PUBLIC_URL, а не из заголовков запроса, — заголовок Host можно подделать"""
    public_url = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
    if public_url:
        return public_url
    host = request.headers.get("host", "localhost:3000")
    proto = request.headers.get("x-forwarded-proto") or ("http" if host.startswith(("localhost", "127.")) else "https")
    return f"{proto}://{host}"


@app.get("/api/premium")
def premium_info(authorization: str = Header(None), s=Depends(get_db)):
    user = current_user(s, authorization)
    return {
        "plans": [{"id": k, **v} for k, v in data.PLANS.items()],
        "free_daily_interests": data.FREE_DAILY_INTERESTS,
        "active": is_premium(user),
        "until": fmt(user.premium_until) if is_premium(user) else None,
        "payment_mode": "yookassa" if yookassa.enabled() else "demo",
        "test_mode": yookassa.is_test(),
    }


class CheckoutIn(BaseModel):
    plan: str = Field(max_length=20)


@app.post("/api/premium/checkout")
def checkout(body: CheckoutIn, request: Request, authorization: str = Header(None), s=Depends(get_db)):
    rate_limit(request, "checkout", limit=10, per_seconds=600)
    user = require_user(s, authorization)
    plan = data.PLANS.get(body.plan)
    if plan is None:
        raise HTTPException(status_code=400, detail="Неизвестный тариф")

    if not yookassa.enabled():
        # демо-режим: сразу включаем подписку
        payment = Payment(login=user.login, plan=body.plan, amount=plan["price"], status="pending", demo=True)
        s.add(payment)
        s.flush()
        activate_payment(s, payment)
        return {"mode": "demo", "active": True, "until": fmt(user.premium_until),
                "message": "Подписка «Соседи+» включена"}

    # ЮKassa: создаём платёж у себя, потом в ЮKassa, и отправляем человека на страницу оплаты
    payment = Payment(login=user.login, plan=body.plan, amount=plan["price"], status="pending", demo=False)
    s.add(payment)
    s.commit()
    return_url = f"{site_origin(request)}/site/premium.html?payment={payment.id}"
    try:
        yk_id, confirmation_url = yookassa.create_payment(
            plan["price"],
            f"Подписка «Соседи+» — {plan['title']}",
            return_url,
            {"payment_id": str(payment.id), "login": user.login, "plan": body.plan},
        )
    except yookassa.YooKassaError as e:
        payment.status = "canceled"
        s.commit()
        print("ЮKassa:", e)
        raise HTTPException(status_code=502, detail="Платёжный сервис сейчас недоступен, попробуй позже")
    payment.yk_id = yk_id
    s.commit()
    return {"mode": "yookassa", "confirmation_url": confirmation_url, "payment_id": payment.id}


@app.get("/api/premium/payments/{payment_id}")
def payment_status(payment_id: int, authorization: str = Header(None), s=Depends(get_db)):
    """Человек вернулся со страницы ЮKassa — проверяем, прошла ли оплата"""
    user = require_user(s, authorization)
    payment = s.get(Payment, payment_id)
    if payment is None or payment.login != user.login:
        raise HTTPException(status_code=404, detail="Платёж не найден")
    try:
        status = sync_payment(s, payment)
    except yookassa.YooKassaError as e:
        print("ЮKassa:", e)
        status = payment.status
    return {"status": status, "premium": is_premium(user), "until": fmt(user.premium_until) if is_premium(user) else None}


@app.post("/api/yookassa/webhook")
async def yookassa_webhook(request: Request, s=Depends(get_db)):
    """Уведомление от ЮKassa об изменении платежа.
    Телу уведомления не доверяем: берём id и сами спрашиваем статус у ЮKassa"""
    rate_limit(request, "webhook", limit=120, per_seconds=60)
    try:
        body = await request.json()
        yk_id = str(body["object"]["id"])[:64]
    except Exception:
        raise HTTPException(status_code=400, detail="Неверное уведомление")
    payment = s.scalar(select(Payment).where(Payment.yk_id == yk_id))
    if payment is not None and yookassa.enabled():
        try:
            sync_payment(s, payment)
        except yookassa.YooKassaError as e:
            print("ЮKassa:", e)
            raise HTTPException(status_code=502, detail="Не удалось проверить платёж")  # ЮKassa пришлёт уведомление ещё раз
    return {"ok": True}


# ============ Жалобы ============

class ReportIn(BaseModel):
    profile_id: int
    reason: str = Field(max_length=20)


@app.post("/api/reports", status_code=201)
def create_report(body: ReportIn, request: Request, authorization: str = Header(None), s=Depends(get_db)):
    rate_limit(request, "report", limit=10, per_seconds=3600)
    user = require_user(s, authorization)
    if s.get(Profile, body.profile_id) is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    if body.reason not in data.REPORT_REASONS:
        raise HTTPException(status_code=400, detail="Неизвестная причина")
    s.add(Report(profile_id=body.profile_id, reason=body.reason, from_login=user.login))
    s.commit()
    return {"message": "Жалоба отправлена"}


# ============ Сайт ============
# Папка docs — это наш фронт. Открывается по адресу /site/
@app.middleware("http")
async def no_stale_site(request, call_next):
    """Страницы, скрипты и стили сайта браузер каждый раз сверяет с сервером,
    чтобы после обновления никто не сидел со старой версией из кэша"""
    response = await call_next(request)
    if request.url.path.startswith("/site"):
        response.headers["Cache-Control"] = "no-cache"
    return add_security_headers(request, response)


app.mount("/site", StaticFiles(directory="docs", html=True), name="site")
