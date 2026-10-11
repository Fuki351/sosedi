# Сервер сайта «Соседи» на FastAPI
# Запуск: uvicorn main:app --reload --port 3000

import random
import re
import secrets
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import data

app = FastAPI(title="Соседи — API", description="Сервер сайта для подбора соседа")


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

def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def find_user(login):
    for user in data.users:
        if user["login"] == login:
            return user
    return None


def current_user(authorization):
    """Достаём пользователя по токену из заголовка Authorization: Bearer <токен>"""
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "")
    login = data.tokens.get(token)
    if login is None:
        return None
    return find_user(login)


def require_user(authorization):
    """То же самое, но если токена нет или он неверный — ошибка 401"""
    user = current_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Нужно войти")
    return user


def find_profile(profile_id):
    for p in data.profiles:
        if p["id"] == profile_id:
            return p
    return None


def profile_of(user):
    """Анкета пользователя (или None, если он её ещё не заполнил)"""
    if user is None:
        return None
    for p in data.profiles:
        if p["owner"] == user["login"]:
            return p
    return None


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
        if diff == 0:
            result = "yes"
        elif diff == 1:
            result = "part"
        else:
            result = "no"
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


def is_mutual(id_a, id_b):
    """Интерес взаимный, если оба отметили друг друга"""
    a_to_b = any(i["from_id"] == id_a and i["to_id"] == id_b for i in data.interests)
    b_to_a = any(i["from_id"] == id_b and i["to_id"] == id_a for i in data.interests)
    return a_to_b and b_to_a


def short_card(p, my):
    """Анкета для списка: без Telegram и без ответов"""
    if p["housing"] == "flat":
        housing_text = "Квартира · " + data.BUDGETS.get(p["budget"], "")
    else:
        housing_text = data.HOUSING[p["housing"]]
    card = {
        "id": p["id"],
        "name": p["name"],
        "course": p["course"],
        "housing": p["housing"],
        "housing_text": housing_text,
        "place": p["place"],
        "tags": make_tags(p["answers"]),
        "match": None,
    }
    if my is not None:
        card["match"] = compatibility(my["answers"], p["answers"])
    return card


# ============ Шаг 6. Логин ============

class LoginIn(BaseModel):
    login: str
    password: str


@app.post("/api/login")
def login(body: LoginIn):
    user = find_user(body.login.strip().lower())
    if user is None or user["password"] != body.password:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = secrets.token_hex(16)  # случайная строка
    data.tokens[token] = user["login"]
    my = profile_of(user)
    return {"token": token, "name": user["name"], "profile_id": my["id"] if my else None}


@app.get("/api/me")
def me(authorization: str = Header(None)):
    user = require_user(authorization)
    my = profile_of(user)
    return {"login": user["login"], "name": user["name"], "profile_id": my["id"] if my else None}


# ============ Шаг 3. REST API для анкет ============

@app.get("/api/profiles")
def list_profiles(housing: str = "all", budget: str = "any",
                  no_smoke: bool = False, no_pets: bool = False,
                  authorization: str = Header(None)):
    user = current_user(authorization)
    my = profile_of(user)

    result = []
    for p in data.profiles:
        if my is not None and p["id"] == my["id"]:
            continue  # себя в списке не показываем
        if housing != "all" and p["housing"] != housing:
            continue
        if budget != "any" and p["budget"] != budget:
            continue
        if no_smoke and p["answers"][5] == 2:
            continue
        if no_pets and p["answers"][6] == 0:
            continue
        result.append(short_card(p, my))

    # если вошёл и есть анкета — сверху самые совместимые
    if my is not None:
        result.sort(key=lambda card: card["match"], reverse=True)
    return result


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: int, authorization: str = Header(None)):
    p = find_profile(profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    user = current_user(authorization)
    my = profile_of(user)

    card = short_card(p, my)
    card["about"] = p["about"]
    card["when"] = p["when"]
    card["budget_text"] = data.BUDGETS.get(p["budget"]) if p["budget"] else None
    card["housing_name"] = data.HOUSING[p["housing"]]
    card["is_mine"] = my is not None and my["id"] == p["id"]
    card["telegram"] = None
    card["interest_sent"] = False
    card["mutual"] = False
    card["compare"] = None

    if my is not None and not card["is_mine"]:
        card["compare"] = compare(my["answers"], p["answers"])
        card["interest_sent"] = any(i["from_id"] == my["id"] and i["to_id"] == p["id"] for i in data.interests)
        card["mutual"] = is_mutual(my["id"], p["id"])
        if card["mutual"]:
            card["telegram"] = p["telegram"]  # контакт только при взаимном интересе

    if card["is_mine"]:
        card["telegram"] = p["telegram"]
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
def create_profile(body: ProfileIn, authorization: str = Header(None)):
    user = require_user(authorization)

    # проверки
    if profile_of(user) is not None:
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

    profile = {
        "id": data.next_ids["profile"],
        "owner": user["login"],
        "name": name,
        "course": body.course,
        "telegram": telegram,
        "housing": body.housing,
        "budget": body.budget,
        "place": body.place.strip() or "Район не указан",
        "when": body.when,
        "about": body.about.strip()[:200],
        "answers": body.answers,
    }
    data.next_ids["profile"] += 1
    data.profiles.append(profile)
    return {"id": profile["id"], "message": "Анкета опубликована"}


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, authorization: str = Header(None)):
    user = require_user(authorization)
    p = find_profile(profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    if p["owner"] != user["login"]:
        raise HTTPException(status_code=403, detail="Удалить можно только свою анкету")

    data.profiles.remove(p)
    # вместе с анкетой удаляем и все отметки, где она участвует
    data.interests[:] = [i for i in data.interests if i["from_id"] != profile_id and i["to_id"] != profile_id]
    return {"message": "Анкета удалена"}


# ============ Шаг 4. Вторая сущность: отметки «Интересно» ============

class InterestIn(BaseModel):
    to_id: int


@app.post("/api/interests", status_code=201)
def create_interest(body: InterestIn, authorization: str = Header(None)):
    user = require_user(authorization)
    my = profile_of(user)
    if my is None:
        raise HTTPException(status_code=400, detail="Сначала заполни свою анкету")
    other = find_profile(body.to_id)
    if other is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    if other["id"] == my["id"]:
        raise HTTPException(status_code=400, detail="Нельзя отметить самого себя")

    already = any(i["from_id"] == my["id"] and i["to_id"] == other["id"] for i in data.interests)
    if not already:
        data.interests.append({
            "id": data.next_ids["interest"],
            "from_id": my["id"],
            "to_id": other["id"],
            "created_at": now_text(),  # дату сервер ставит сам
        })
        data.next_ids["interest"] += 1

    mutual = is_mutual(my["id"], other["id"])
    return {"mutual": mutual, "telegram": other["telegram"] if mutual else None}


@app.get("/api/interests")
def list_interests():
    """Все отметки. Вместо id сервер подставляет имена из анкет (ручной аналог JOIN)"""
    result = []
    for i in data.interests:
        a = find_profile(i["from_id"])
        b = find_profile(i["to_id"])
        result.append({
            "id": i["id"],
            "from_id": i["from_id"],
            "from_name": a["name"] if a else "—",
            "to_id": i["to_id"],
            "to_name": b["name"] if b else "—",
            "created_at": i["created_at"],
        })
    return result


@app.get("/api/interests/my")
def my_interests(authorization: str = Header(None)):
    """«Мои отметки»: только те, что поставил текущий пользователь"""
    user = require_user(authorization)
    my = profile_of(user)
    if my is None:
        return {"sent": [], "received_count": 0}

    sent = []
    for i in data.interests:
        if i["from_id"] != my["id"]:
            continue
        other = find_profile(i["to_id"])
        if other is None:
            continue
        mutual = is_mutual(my["id"], other["id"])
        sent.append({
            "profile_id": other["id"],
            "name": other["name"],
            "match": compatibility(my["answers"], other["answers"]),
            "mutual": mutual,
            "telegram": other["telegram"] if mutual else None,
            "created_at": i["created_at"],
        })
    received = sum(1 for i in data.interests if i["to_id"] == my["id"])
    return {"sent": sent, "received_count": received}


# ============ Жалобы ============

class ReportIn(BaseModel):
    profile_id: int
    reason: str


@app.post("/api/reports", status_code=201)
def create_report(body: ReportIn, authorization: str = Header(None)):
    user = require_user(authorization)
    if find_profile(body.profile_id) is None:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    if body.reason not in data.REPORT_REASONS:
        raise HTTPException(status_code=400, detail="Неизвестная причина")
    data.reports.append({
        "id": data.next_ids["report"],
        "profile_id": body.profile_id,
        "reason": body.reason,
        "from": user["login"],
        "created_at": now_text(),
    })
    data.next_ids["report"] += 1
    return {"message": "Жалоба отправлена"}


# ============ Сайт ============
# Папка docs — это наш фронт (так она называется, чтобы GitHub Pages тоже мог её показать). Открывается по адресу /site/
app.mount("/site", StaticFiles(directory="docs", html=True), name="site")
