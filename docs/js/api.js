// Общие функции для запросов к нашему серверу

function getToken() {
  return localStorage.getItem('token');
}

function getName() {
  return localStorage.getItem('name');
}

function logout() {
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

// текст ошибки из ответа сервера
function errorText(result) {
  if (result.data && typeof result.data.detail === 'string') {
    return result.data.detail;
  }
  return 'Что-то пошло не так, попробуй ещё раз';
}
