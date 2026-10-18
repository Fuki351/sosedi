// Общие функции для запросов к нашему серверу

function getToken() {
  return localStorage.getItem('token');
}

function getName() {
  return localStorage.getItem('name');
}

function logout() {
  // просим сервер закрыть сессию, чтобы украденный токен тоже перестал работать
  const token = localStorage.getItem('token');
  if (token) {
    fetch('/api/logout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + token }, keepalive: true }).catch(function () {});
  }
  localStorage.removeItem('token');
  localStorage.removeItem('name');
}

// api('/profiles') делает запрос на /api/profiles и сразу добавляет токен, если мы вошли
async function api(path, options) {
  options = options || {};
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) {
    headers['Authorization'] = 'Bearer ' + token;
  }

  let response;
  try {
    response = await fetch('/api' + path, {
      method: options.method || 'GET',
      headers: headers,
      body: options.body ? JSON.stringify(options.body) : undefined
    });
  } catch (e) {
    return { ok: false, status: 0, data: { detail: 'Сервер не отвечает. Он запущен?' } };
  }

  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    data = null;
  }

  // сервер перезапустили — старый токен больше не действует
  if (response.status === 401 && token) {
    logout();
  }

  return { ok: response.ok, status: response.status, data: data };
}

// загрузка файла (фото) на сервер — отправляем как форму, а не JSON
async function apiUpload(path, file) {
  const form = new FormData();
  form.append('file', file);
  const headers = {};
  const token = getToken();
  if (token) {
    headers['Authorization'] = 'Bearer ' + token;
  }
  try {
    const response = await fetch('/api' + path, { method: 'POST', headers: headers, body: form });
    let data = null;
    try { data = await response.json(); } catch (e) { data = null; }
    return { ok: response.ok, status: response.status, data: data };
  } catch (e) {
    return { ok: false, status: 0, data: { detail: 'Сервер не отвечает. Он запущен?' } };
  }
}

// экранируем текст от пользователя, чтобы его нельзя было вставить как HTML
function esc(text) {
  return String(text == null ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// цвет заглушки без фото — свой у каждой анкеты
function avatarColor(id) {
  const hues = [214, 250, 160, 20, 330, 190, 280, 40];
  const h = hues[(Number(id) || 0) % hues.length];
  return `linear-gradient(135deg, hsl(${h} 90% 90%), hsl(${(h + 30) % 360} 75% 78%))`;
}

// круглая аватарка: фото или первая буква имени
function avatarHtml(p, extraClass) {
  const cls = 'avatar ' + (extraClass || '');
  if (p.photo) {
    return `<img class="${cls} avatar--photo" src="${p.photo}" alt="${esc(p.name)}">`;
  }
  return `<span class="${cls} avatar--letter" style="background:${avatarColor(p.id || p.profile_id)}">${esc((p.name || '?')[0])}</span>`;
}

// текст ошибки из ответа сервера
function errorText(result) {
  if (result.data && typeof result.data.detail === 'string') {
    return result.data.detail;
  }
  return 'Что-то пошло не так, попробуй ещё раз';
}
