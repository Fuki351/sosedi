// «Мои отметки»: только записи текущего пользователя

// без входа здесь делать нечего
if (!getToken()) {
  window.location.href = 'login.html?next=my.html';
}

const content = document.getElementById('my-content');
const loadError = document.getElementById('load-error');
let myProfileId = null;

async function loadMy() {
  const me = await api('/me');
  if (!me.ok) {
    window.location.href = 'login.html?next=my.html';
    return;
  }

  document.getElementById('my-who').textContent = 'Ты вошёл как ' + me.data.name + ' (' + me.data.login + ')';
  myProfileId = me.data.profile_id;

  // своя анкета есть или нет
  document.getElementById('my-profile-yes').hidden = myProfileId === null;
  document.getElementById('my-profile-no').hidden = myProfileId !== null;
  if (myProfileId !== null) {
    document.getElementById('my-profile-link').href = 'profile.html?id=' + myProfileId;
  }

  const result = await api('/interests/my');
  if (!result.ok) {
    loadError.textContent = errorText(result);
    loadError.hidden = false;
    return;
  }

  const count = result.data.received_count;
  document.getElementById('received').textContent = count > 0
    ? 'Тебя отметили «Интересно»: ' + count
    : '';

  renderList(result.data.sent);
  content.hidden = false;
}

function renderList(sent) {
  const list = document.getElementById('my-list');
  list.innerHTML = '';
  document.getElementById('my-empty').hidden = sent.length > 0;

  sent.forEach(function (item) {
    let status = '<span class="result result--part">Ждём ответа</span>';
    let contact = '';
    if (item.mutual) {
      status = '<span class="result result--yes">Взаимно</span>';
      contact = '<p class="my-list__contact">Telegram: <b>' + item.telegram + '</b></p>';
    }

    list.innerHTML += `
      <li class="my-list__item">
        <div>
          <a href="profile.html?id=${item.profile_id}" class="my-list__name">${item.name}</a>
          <p class="my-list__info">Совместимость ${item.match}% · отмечено ${item.created_at}</p>
          ${contact}
        </div>
        ${status}
      </li>`;
  });
}

// удаление своей анкеты, сначала спрашиваем подтверждение
document.getElementById('delete-btn').addEventListener('click', function () {
  document.getElementById('confirm-block').hidden = false;
});

document.getElementById('confirm-no').addEventListener('click', function () {
  document.getElementById('confirm-block').hidden = true;
});

document.getElementById('confirm-yes').addEventListener('click', async function () {
  const result = await api('/profiles/' + myProfileId, { method: 'DELETE' });
  if (!result.ok) {
    loadError.textContent = errorText(result);
    loadError.hidden = false;
    return;
  }
  document.getElementById('confirm-block').hidden = true;
  loadMy();
});

document.getElementById('logout-btn').addEventListener('click', function () {
  logout();
  window.location.href = 'index.html';
});

loadMy();
