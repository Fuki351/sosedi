# Защита сайта: заголовки безопасности и ограничение частоты запросов

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# ===== Заголовки безопасности =====
# CSP разрешает скрипты только с нашего сайта: даже если кто-то подсунет <script> в анкету,
# браузер его не выполнит. Стили и шрифты — ещё с Google Fonts.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "form-action 'self' https://yoomoney.ru https://*.yoomoney.ru",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "object-src 'none'",
])

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",           # браузер не угадывает тип файла
    "X-Frame-Options": "DENY",                     # сайт нельзя встроить в чужую страницу (кликджекинг)
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",  # только HTTPS
    "Cross-Origin-Opener-Policy": "same-origin",
}


def add_security_headers(request: Request, response):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    path = request.url.path
    if path.startswith("/site") or path == "/":
        response.headers.setdefault("Content-Security-Policy", CSP)
    if path.startswith("/api/") and not path.startswith("/api/photos/"):
        response.headers["Cache-Control"] = "no-store"  # личные данные не оседают в кэше браузера и прокси
    return response


# ===== Ограничение частоты запросов =====
# Храним в памяти, когда с какого адреса приходили запросы. Для одного сервера на Render этого достаточно.
_hits = defaultdict(deque)


def client_ip(request: Request):
    """Настоящий адрес посетителя: Render ставит его первым в X-Forwarded-For"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, action: str, limit: int, per_seconds: int, key: str | None = None):
    """Не больше limit запросов за per_seconds секунд с одного адреса (или по своему ключу).
    Защищает от подбора паролей, спама регистрациями, жалобами и загрузками"""
    bucket = f"{action}:{key or client_ip(request)}"
    now = time.monotonic()
    hits = _hits[bucket]
    while hits and now - hits[0] > per_seconds:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail="Слишком много попыток. Подожди немного и попробуй снова")
    hits.append(now)
    if len(_hits) > 50_000:  # чтобы память не росла бесконечно
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > 3600]:
            del _hits[k]
