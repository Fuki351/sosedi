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

  // подписка
  document.getElementById('plus-yes').hidden = !me.data.premium;
  document.getElementById('plus-no').hidden = me.data.premium;
  if (me.data.premium) {
    const d = me.data.premium_until.slice(0, 10).split('-');
    document.getElementById('plus-until').textContent = 'Активна до ' + d[2] + '.' + d[1] + '.' + d[0];
  } else {
    document.getElementById('left-today').textContent = me.data.interests_left;
  }
  myProfileId = me.data.profile_id;
  document.getElementById('my-incomplete').hidden = !me.data.profile_incomplete;

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


  renderList(result.data.sent);
  renderReceived(result.data);
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
      contact = '<p class="my-list__contact">Telegram: <b>' + esc(item.telegram) + '</b></p>';
    }

    list.innerHTML += `
      <li class="my-list__item">
        ${avatarHtml(item, 'avatar--small')}
        <div class="my-list__main">
          <a href="profile.html?id=${item.profile_id}" class="my-list__name">${esc(item.name)}</a>
          <p class="my-list__info">Совместимость ${item.match}% · отмечено ${item.created_at}</p>
          ${contact}
        </div>
        ${status}
      </li>`;
  });
}

// «Кто отметил меня»: список — с подпиской, без неё — только число
function word(n) {
  if (n % 10 === 1 && n % 100 !== 11) return 'человек';
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return 'человека';
  return 'человек';
}

function renderReceived(info) {
  const list = document.getElementById('received-list');
  const locked = document.getElementById('received-locked');
  list.innerHTML = '';
  document.getElementById('received-empty').hidden = info.received_count > 0;
  locked.hidden = true;

  if (info.received === null) {
    if (info.received_count > 0) {
      document.getElementById('locked-count').textContent =
        'Тебя отметили: ' + info.received_count + ' ' + word(info.received_count);
      let faces = '';
      for (let i = 0; i < Math.min(info.received_count, 4); i++) {
        faces += '<span class="locked__face" style="background:' + avatarColor(i + 3) + '"></span>';
      }
      document.getElementById('locked-faces').innerHTML = faces;
      locked.hidden = false;
    }
    return;
  }

  info.received.forEach(function (item) {
    const status = item.mutual
      ? '<span class="result result--yes">Взаимно</span>'
      : `<a href="profile.html?id=${item.profile_id}" class="btn btn--small">Ответить</a>`;
    list.innerHTML += `
      <li class="my-list__item">
        ${avatarHtml(item, 'avatar--small')}
        <div class="my-list__main">
          <a href="profile.html?id=${item.profile_id}" class="my-list__name">${esc(item.name)}</a>
          <p class="my-list__info">Совместимость ${item.match}% · отметил(а) ${item.created_at}</p>
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
  // удаление аккаунта целиком — с подтверждением паролем
const deleteForm = document.getElementById('delete-account-form');
document.getElementById('delete-account-btn').addEventListener('click', function () {
  deleteForm.hidden = false;
});
document.getElementById('delete-cancel').addEventListener('click', function () {
  deleteForm.hidden = true;
});
deleteForm.addEventListener('submit', async function (event) {
  event.preventDefault();
  const errorBox = document.getElementById('delete-error');
  const result = await api('/me/delete', { method: 'POST', body: { password: document.getElementById('delete-password').value } });
  if (!result.ok) {
    errorBox.textContent = errorText(result);
    errorBox.hidden = false;
    return;
  }
  localStorage.removeItem('token');
  localStorage.removeItem('name');
  window.location.href = 'index.html';
});

loadMy();
});

document.getElementById('logout-btn').addEventListener('click', function () {
  logout();
  window.location.href = 'index.html';
});

// удаление аккаунта целиком — с подтверждением паролем
const deleteForm = document.getElementById('delete-account-form');
document.getElementById('delete-account-btn').addEventListener('click', function () {
  deleteForm.hidden = false;
});
document.getElementById('delete-cancel').addEventListener('click', function () {
  deleteForm.hidden = true;
});
deleteForm.addEventListener('submit', async function (event) {
  event.preventDefault();
  const errorBox = document.getElementById('delete-error');
  const result = await api('/me/delete', { method: 'POST', body: { password: document.getElementById('delete-password').value } });
  if (!result.ok) {
    errorBox.textContent = errorText(result);
    errorBox.hidden = false;
    return;
  }
  localStorage.removeItem('token');
  localStorage.removeItem('name');
  window.location.href = 'index.html';
});

loadMy();
