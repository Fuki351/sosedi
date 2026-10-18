# Работа с ЮKassa (yookassa.ru): создаём платёж и узнаём его статус.
# Ключи берём из переменных окружения (на Render — Environment):
#   YOOKASSA_SHOP_ID     — shopId магазина
#   YOOKASSA_SECRET_KEY  — секретный ключ (у тестового магазина начинается с test_)
# Если ключей нет, сайт работает в демо-режиме, как раньше.

import base64
import json
import os
import urllib.error
import urllib.request
import uuid

API_URL = "https://api.yookassa.ru/v3/payments"


def shop_id():
    return os.environ.get("YOOKASSA_SHOP_ID", "").strip()


def secret_key():
    return os.environ.get("YOOKASSA_SECRET_KEY", "").strip()


def enabled():
    return bool(shop_id() and secret_key())


def is_test():
    return secret_key().startswith("test_")


class YooKassaError(Exception):
    pass


def _request(method, url, body=None):
    """Запрос к API ЮKassa. Авторизация: shopId и секретный ключ (Basic Auth)"""
    auth = base64.b64encode(f"{shop_id()}:{secret_key()}".encode()).decode()
    headers = {"Authorization": "Basic " + auth, "Content-Type": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        # ключ идемпотентности: если запрос повторится, ЮKassa не создаст второй платёж
        headers["Idempotence-Key"] = str(uuid.uuid4())
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise YooKassaError(f"ЮKassa ответила {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise YooKassaError(f"Не удалось связаться с ЮKassa: {e.reason}")


def create_payment(amount_rub, description, return_url, metadata):
    """Создаём платёж. В ответе — id платежа и ссылка на страницу оплаты ЮKassa"""
    payment = _request("POST", API_URL, {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "capture": True,  # списываем деньги сразу, без отдельного подтверждения
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description[:128],
        "metadata": metadata,
    })
    return payment["id"], payment["confirmation"]["confirmation_url"]


def get_payment(payment_id):
    """Статус платежа прямо из ЮKassa: pending / waiting_for_capture / succeeded / canceled"""
    return _request("GET", f"{API_URL}/{payment_id}")
