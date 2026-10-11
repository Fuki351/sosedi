// Вход: отправляем логин и пароль на сервер, он возвращает токен

const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');

// куда вернуть после входа (например, обратно на анкету)
const nextPage = new URLSearchParams(window.location.search).get('next') || 'catalog.html';

loginForm.addEventListener('submit', async function (event) {
  event.preventDefault();

  const login = document.getElementById('login').value.trim();
  const password = document.getElementById('password').value;

  if (login === '' || password === '') {
    loginError.textContent = 'Введи логин и пароль';
    loginError.hidden = false;
    return;
  }

  const result = await api('/login', { method: 'POST', body: { login: login, password: password } });

  if (!result.ok) {
    loginError.textContent = errorText(result);
    loginError.hidden = false;
    return;
  }

  // запоминаем токен в браузере — дальше он уходит с каждым запросом
  localStorage.setItem('token', result.data.token);
  localStorage.setItem('name', result.data.name);
  window.location.href = nextPage;
});
