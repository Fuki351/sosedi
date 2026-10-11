// Меню на телефоне: по нажатию на бургер показываем или прячем ссылки
const burger = document.getElementById('burger');
const menu = document.getElementById('menu');

burger.addEventListener('click', function () {
  menu.classList.toggle('menu--open');
});

// если нажали на ссылку в меню, закрываем его
const menuLinks = menu.querySelectorAll('a');

menuLinks.forEach(function (link) {
  link.addEventListener('click', function () {
    menu.classList.remove('menu--open');
  });
});

// если пользователь вошёл, вместо «Войти» показываем его имя (ссылка на «Мои отметки»)
const loginLink = document.getElementById('login-link');

if (loginLink && localStorage.getItem('token')) {
  loginLink.textContent = localStorage.getItem('name') || 'Мои отметки';
  loginLink.href = 'my.html';
}
