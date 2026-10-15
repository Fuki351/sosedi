// Карточка соседа: загружаем анкету с сервера по id из адреса (profile.html?id=1)
// Кнопки: «Интересно», «Скрыть», «Пожаловаться»

const params = new URLSearchParams(window.location.search);
const profileId = Number(params.get('id')) || 1;

const profile = document.getElementById('profile');
const loadError = document.getElementById('load-error');
const interestBtn = document.getElementById('interest-btn');
const sentBlock = document.getElementById('sent-block');
const mutualBlock = document.getElementById('mutual-block');
const actionError = document.getElementById('action-error');

// если не вошли — отправляем на вход, а потом вернём обратно на эту анкету
function goLogin() {
  window.location.href = 'login.html?next=' + encodeURIComponent('profile.html?id=' + profileId);
}

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

async function loadProfile() {
  const result = await api('/profiles/' + profileId);
  if (!result.ok) {
    loadError.textContent = errorText(result);
    loadError.hidden = false;
    return;
  }
  fill(result.data);
}

function fill(p) {
  document.title = p.name + ' — Соседи';
  showPhoto(p);
  setText('p-name', p.name);
  document.getElementById('p-plus').hidden = !p.premium;
  setText('p-course', p.course + ' курс');
  setText('p-housing', p.housing_name);
  setText('p-university', p.university || '—');
  setText('p-seek', p.seek_text || '—');
  setText('p-budget', p.budget_text || '—');
  setText('p-place', p.place);
  setText('p-when', p.when || '—');
  setText('p-about', p.about || 'Пока ничего не написал(а).');
  setText('other-name', p.name);

  // своя анкета: кнопки не нужны
  if (p.is_mine) {
    document.getElementById('actions').hidden = true;
    document.getElementById('mine-block').hidden = false;
    document.getElementById('photo-edit').hidden = false;
    profile.classList.add('profile--mine');
  }

  // состояние «Интересно»
  if (p.mutual) {
    showMutual(p.telegram);
  } else if (p.interest_sent) {
    interestBtn.hidden = true;
    sentBlock.hidden = false;
  }

  // без таблицы совместимости показываем просто ответы человека
  if (!p.compare && p.answers_text && p.answers_text.length) {
    let habits = '';
    p.answers_text.forEach(function (row) {
      habits += '<li><span>' + esc(row.question) + '</span><b>' + esc(row.answer) + '</b></li>';
    });
    document.getElementById('p-habits').innerHTML = habits;
    document.getElementById('habits-block').hidden = false;
  }

  // совместимость сервер присылает, только если мы вошли и у нас есть анкета
  if (p.compare) {
    showCompare(p.match, p.compare);
  } else if (!p.is_mine) {
    document.getElementById('match-login').hidden = false;
    if (getToken()) {
      setText('match-login-text', 'Заполни свою анкету, и сервер посчитает, насколько вы подходите друг другу.');
      setText('match-login-btn', 'Заполнить анкету');
      document.getElementById('match-login-btn').href = 'anketa.html';
    }
  }

  profile.hidden = false;
}

// большое фото анкеты или заглушка с буквой
let currentProfile = null;

function showPhoto(p) {
  currentProfile = p;
  const box = document.getElementById('p-photo');
  if (p.photo) {
    box.innerHTML = `<img src="${p.photo}" alt="${esc(p.name)}">`;
    box.style.background = '';
  } else {
    box.innerHTML = `<span>${esc(p.name[0])}</span>`;
    box.style.background = avatarColor(p.id);
  }
  document.getElementById('photo-btn-text').textContent = p.photo ? 'Сменить фото' : 'Загрузить фото';
  document.getElementById('photo-delete').hidden = !p.photo;
}

// своя анкета: загрузка фото
const photoInput = document.getElementById('photo-input');
const photoError = document.getElementById('photo-error');

photoInput.addEventListener('change', async function () {
  const file = photoInput.files[0];
  if (!file) return;
  photoError.hidden = true;
  if (file.size > 8 * 1024 * 1024) {
    photoError.textContent = 'Фото больше 8 МБ, выбери поменьше';
    photoError.hidden = false;
    return;
  }
  document.getElementById('photo-btn-text').textContent = 'Загружаем…';
  const result = await apiUpload('/profiles/' + profileId + '/photo', file);
  photoInput.value = '';
  if (!result.ok) {
    photoError.textContent = errorText(result);
    photoError.hidden = false;
    showPhoto(currentProfile);
    return;
  }
  currentProfile.photo = result.data.photo;
  showPhoto(currentProfile);
});

document.getElementById('photo-delete').addEventListener('click', async function () {
  const result = await api('/profiles/' + profileId + '/photo', { method: 'DELETE' });
  if (result.ok) {
    currentProfile.photo = null;
    showPhoto(currentProfile);
  }
});

function showMutual(telegram) {
  interestBtn.hidden = true;
  sentBlock.hidden = true;
  mutualBlock.hidden = false;
  setText('p-telegram', telegram);
}

const resultText = { yes: 'Совпадает', part: 'Похоже', no: 'Разное' };

function showCompare(match, rows) {
  setText('match-percent', match + '%');
  document.getElementById('match-bar').style.width = match + '%';

  let yes = 0;
  let part = 0;
  let no = 0;
  let html = '';
  rows.forEach(function (row) {
    if (row.result === 'yes') yes++;
    if (row.result === 'part') part++;
    if (row.result === 'no') no++;
    html += `
      <tr>
        <td>${row.question}</td>
        <td>${row.me}</td>
        <td>${row.other}</td>
        <td><span class="result result--${row.result}">${resultText[row.result]}</span></td>
      </tr>`;
  });
  document.getElementById('compare-rows').innerHTML = html;
  setText('match-summary', 'Совпадает: ' + yes + ' · Похоже: ' + part + ' · Разное: ' + no);
  document.getElementById('match-block').hidden = false;
}

// нажали «Интересно» — отправляем на сервер, он скажет, взаимно или нет
interestBtn.addEventListener('click', async function () {
  if (!getToken()) {
    goLogin();
    return;
  }
  actionError.hidden = true;
  interestBtn.disabled = true;

  const result = await api('/interests', { method: 'POST', body: { to_id: profileId } });
  interestBtn.disabled = false;

  if (result.status === 402) {
    // лимит бесплатных отметок на сегодня
    interestBtn.hidden = true;
    document.getElementById('limit-block').hidden = false;
    return;
  }
  if (!result.ok) {
    actionError.textContent = errorText(result);
    actionError.hidden = false;
    return;
  }
  if (result.data.mutual) {
    showMutual(result.data.telegram);
  } else {
    interestBtn.hidden = true;
    sentBlock.hidden = false;
  }
});

// скрыть анкету (только у себя на странице)
const hiddenBlock = document.getElementById('hidden-block');

document.getElementById('hide-btn').addEventListener('click', function () {
  profile.hidden = true;
  hiddenBlock.hidden = false;
});

document.getElementById('unhide-btn').addEventListener('click', function () {
  profile.hidden = false;
  hiddenBlock.hidden = true;
});

// жалоба уходит на сервер
const reportForm = document.getElementById('report-form');
const reportError = document.getElementById('report-error');
const reportDone = document.getElementById('report-done');

document.getElementById('report-btn').addEventListener('click', function () {
  if (!getToken()) {
    goLogin();
    return;
  }
  reportForm.hidden = false;
  reportDone.hidden = true;
});

document.getElementById('report-cancel').addEventListener('click', function () {
  reportForm.hidden = true;
  reportError.hidden = true;
});

reportForm.addEventListener('submit', async function (event) {
  event.preventDefault(); // чтобы страница не перезагрузилась

  const reason = document.querySelector('input[name="reason"]:checked');
  if (!reason) {
    reportError.textContent = 'Выбери причину';
    reportError.hidden = false;
    return;
  }

  const result = await api('/reports', { method: 'POST', body: { profile_id: profileId, reason: reason.value } });
  if (!result.ok) {
    reportError.textContent = errorText(result);
    reportError.hidden = false;
    return;
  }

  reportForm.reset();
  reportForm.hidden = true;
  reportError.hidden = true;
  reportDone.hidden = false;
});

loadProfile();
