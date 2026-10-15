# Сервер сайта «Соседи» на FastAPI
# Запуск: uvicorn main:app --reload --port 3000
# Данные хранятся в базе: локально SQLite (файл sosedi.db), на хостинге PostgreSQL (Neon)

import io
import random
import re
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select

import data
from db import (Interest, Payment, Photo, Profile, Report, SessionLocal, Token, User,
                check_password, hash_password, init_db)

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


def current_user(s, authorization):
    """Достаём пользователя по токену из заголовка Authorization: Bearer <токен>"""
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "")
    row = s.get(Token, token)
    if row is None:
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
    for a, b in zip(answers_a, answers_b):
        diff = abs(a - b)
        if diff == 0:
            score += 1
        elif diff == 1:
            score += 0.5
    return round(score / len(answers_a) * 100)


def compare(answers_me, answers_other):
    """Таблица сравнения по каждому вопросу для карточки"""
    rows = []
    for i, question in enumerate(data.QUESTIONS):
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
        "photo": photo_url(p),
        "premium": p.owner in premium_set,
        "match": compatibility(my.answers, p.answers) if my is not None else None,
    }


# ============ Шаг 6. Вход и регистрация ============

def new_token(s, user):
    token = secrets.token_hex(16)  # случайная строка
    s.add(Token(token=token, login=user.login))
    s.commit()
    return token


class LoginIn(BaseModel):
    login: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, s=Depends(get_db)):
    user = s.get(User, body.login.strip().lower())
    if user is None or not check_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = new_token(s, user)
    my = profile_of(s, user)
    return {"token": token, "name": user.name, "profile_id": my.id if my else None}


class RegisterIn(BaseModel):
    login: str
    password: str
    name: str


@app.post("/api/register", status_code=201)
def register(body: RegisterIn, s=Depends(get_db)):
    login_ = body.login.strip().lower()
    name = body.name.strip()
    if not re.fullmatch(r"[a-z0-9_]{3,20}", login_):
        raise HTTPException(status_code=400, detail="Логин: 3–20 символов, латиница, цифры и _")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Пароль — минимум 6 символов")
    if name == "" or len(name) > 40:
        raise HTTPException(status_code=400, detail="Имя должно быть от 1 до 40 символов")
    if s.get(User, login_) is not None:
        raise HTTPException(status_code=409, detail="Такой логин уже занят")
    user = User(login=login_, name=name, password_hash=hash_password(body.password))
    s.add(user)
    s.commit()
    return {"token": new_token(s, user), "name": user.name, "profile_id": None}


@app.get("/api/me")
def me(authorization: str = Header(None), s=Depends(get_db)):
    user = require_user(s, authorization)
    my = profile_of(s, user)
    return {
        "login": user.login,
        "name": user.name,
        "profile_id": my.id if my else None,
        "premium": is_premium(user),
        "premium_until": fmt(user.premium_until) if is_premium(user) else None,
        "interests_left": interests_left(s, user, my),
    }


# ============ Шаг 3. REST API для анкет ============

@app.get("/api/profiles")
def list_profiles(housing: str = "all", budget: str = "any",
                  no_smoke: bool = False, no_pets: bool = False,
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

    result = []
    for p in s.scalars(query):
        if no_smoke and p.answers[5] == 2:
            continue
        if no_pets and p.answers[6] == 0:
            continue
        result.append(short_card(p, my, premium_set))

    # анкеты с «Соседи+» поднимаются наверх, дальше — самые совместимые
    result.sort(key=lambda c: (c["premium"], c["match"] or 0), reverse=True)
    return result


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
    return card


class ProfileIn(BaseModel):
    name: str
    course: int
    telegram: str
    about: str = ""
    housing: str
    budget: str
    place: str = ""
    when: str = ""
    answers: list[int]


@app.post("/api/profiles", status_code=201)
def create_profile(body: ProfileIn, authorization: str = Header(None), s=Depends(get_db)):
    user = require_user(s, authorization)

    # проверки
    if profile_of(s, user) is not None:
        raise HTTPException(status_code=409, detail="У тебя уже есть анкета. Сначала удали старую")
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
    if len(body.answers) != 9 or any(a not in (0, 1, 2) for a in body.answers):
        raise HTTPException(status_code=400, detail="Нужны ответы на все 9 вопросов")
    if body.housing not in data.HOUSING:
        raise HTTPException(status_code=400, detail="Неизвестный тип жилья")
    if body.budget not in data.BUDGETS:
        raise HTTPException(status_code=400, detail="Неизвестный бюджет")

    profile = Profile(
        owner=user.login,
        name=name,
        course=body.course,
        telegram=telegram,
        housing=body.housing,
        budget=body.budget,
        place=body.place.strip()[:80] or "Район не указан",
        when=body.when[:40],
        about=body.about.strip()[:200],
        answers=body.answers,
    )
    s.add(profile)
    s.commit()
    return {"id": profile.id, "message": "Анкета опубликована"}


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, authorization: str = Header(None), s=Depends(get_db)):
    user = require_user(s, authorization)
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
async def upload_photo(profile_id: int, file: UploadFile = File(...),
                       authorization: str = Header(None), s=Depends(get_db)):
    user = require_user(s, authorization)
    p = s.get(Profile, profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    if p.owner != user.login:
        raise HTTPException(status_code=403, detail="Фото можно менять только у своей анкеты")

    raw = await file.read()
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Фото больше 8 МБ")
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)  # чтобы фото с телефона не было повёрнуто
    except Exception:
        raise HTTPException(status_code=400, detail="Это не картинка. Подойдут JPG, PNG или WEBP")

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
    return Response(photo.data, media_type=photo.mime,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ============ Шаг 4. Вторая сущность: отметки «Интересно» ============

class InterestIn(BaseModel):
    to_id: int


@app.post("/api/interests", status_code=201)
def create_interest(body: InterestIn, authorization: str = Header(None), s=Depends(get_db)):
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
def list_interests(s=Depends(get_db)):
    """Все отметки. Вместо id сервер подставляет имена из анкет (ручной аналог JOIN)"""
    result = []
    for i in s.scalars(select(Interest).order_by(Interest.id)):
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

@app.get("/api/premium")
def premium_info(authorization: str = Header(None), s=Depends(get_db)):
    user = current_user(s, authorization)
    return {
        "plans": [{"id": k, **v} for k, v in data.PLANS.items()],
        "free_daily_interests": data.FREE_DAILY_INTERESTS,
        "active": is_premium(user),
        "until": fmt(user.premium_until) if is_premium(user) else None,
    }


class CheckoutIn(BaseModel):
    plan: str


@app.post("/api/premium/checkout")
def checkout(body: CheckoutIn, authorization: str = Header(None), s=Depends(get_db)):
    """Демо-оплата: настоящие деньги не списываются.
    В рабочей версии здесь будет переход на платёжный сервис (например, ЮKassa),
    а подписка включится, когда сервис пришлёт подтверждение оплаты."""
    user = require_user(s, authorization)
    plan = data.PLANS.get(body.plan)
    if plan is None:
        raise HTTPException(status_code=400, detail="Неизвестный тариф")

    start = user.premium_until if is_premium(user) else datetime.now()
    user.premium_until = start + timedelta(days=plan["days"])  # продлеваем, если уже есть
    s.add(Payment(login=user.login, plan=body.plan, amount=plan["price"]))
    s.commit()
    return {"active": True, "until": fmt(user.premium_until), "message": "Подписка «Соседи+» включена"}


# ============ Жалобы ============

class ReportIn(BaseModel):
    profile_id: int
    reason: str


@app.post("/api/reports", status_code=201)
def create_report(body: ReportIn, authorization: str = Header(None), s=Depends(get_db)):
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
app.mount("/site", StaticFiles(directory="docs", html=True), name="site")
