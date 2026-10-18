// Вход и регистрация: отправляем данные на сервер, он возвращает токен

const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const pageParams = new URLSearchParams(window.location.search);

// куда вернуть после входа (например, обратно на анкету)
const nextPage = pageParams.get('next') || 'catalog.html';
let mode = pageParams.get('mode') === 'register' ? 'register' : 'login';

// переключаем вкладки «Вход» / «Регистрация»
function setMode(m) {
  mode = m;
  const reg = mode === 'register';
  document.getElementById('tab-login').classList.toggle('auth-tabs__btn--active', !reg);
  document.getElementById('tab-register').classList.toggle('auth-tabs__btn--active', reg);
  document.getElementById('auth-title').textContent = reg ? 'Регистрация' : 'Вход';
  document.getElementById('auth-desc').textContent = reg
    ? 'Аккаунт нужен, чтобы опубликовать анкету и отмечать тех, кто понравился.'
    : 'Войди, чтобы видеть совместимость и отмечать анкеты.';
  document.getElementById('name-field').hidden = !reg;
  document.getElementById('password-hint').hidden = !reg;
  document.getElementById('consent-field').hidden = !reg;
  document.getElementById('demo-accounts').hidden = reg;
  document.getElementById('login-btn').textContent = reg ? 'Создать аккаунт' : 'Войти';
  document.getElementById('password').autocomplete = reg ? 'new-password' : 'current-password';
  loginError.hidden = true;
}

document.getElementById('tab-login').addEventListener('click', function () { setMode('login'); });
document.getElementById('tab-register').addEventListener('click', function () { setMode('register'); });
setMode(mode);

loginForm.addEventListener('submit', async function (event) {
  event.preventDefault();

  const login = document.getElementById('login').value.trim();
  const password = document.getElementById('password').value;
  const name = document.getElementById('reg-name').value.trim();

  if (login === '' || password === '' || (mode === 'register' && name === '')) {
    loginError.textContent = mode === 'register' ? 'Заполни имя, логин и пароль' : 'Введи логин и пароль';
    loginError.hidden = false;
    return;
  }

  if (mode === 'register' && !document.getElementById('consent').checked) {
    loginError.textContent = 'Отметь согласие с офертой и политикой конфиденциальности';
    loginError.hidden = false;
    return;
  }

  const result = mode === 'register'
    ? await api('/register', { method: 'POST', body: { login: login, password: password, name: name } })
    : await api('/login', { method: 'POST', body: { login: login, password: password } });

  if (!result.ok) {
    loginError.textContent = errorText(result);
    loginError.hidden = false;
    return;
  }

  // запоминаем токен в браузере — дальше он уходит с каждым запросом
  localStorage.setItem('token', result.data.token);
  localStorage.setItem('name', result.data.name);
  // после регистрации анкеты ещё нет — сразу ведём её заполнять
  window.location.href = (mode === 'register' && !pageParams.get('next')) ? 'anketa.html' : nextPage;
});
