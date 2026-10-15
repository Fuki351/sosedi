// Анкета из 4 шагов: показываем один шаг, проверяем поля, идём дальше.
// Если в адресе ?edit=1 — открываем свою анкету и сохраняем изменения (PUT), а не создаём новую.

let step = 1;
let questions = [];   // вопросы приходят с сервера
let editId = null;    // id своей анкеты в режиме редактирования
const isEdit = new URLSearchParams(window.location.search).get('edit') === '1';

const steps = document.querySelectorAll('.form-step');
const stepperItems = document.querySelectorAll('.stepper__item');
const stepNumber = document.getElementById('step-number');
const errorBox = document.getElementById('form-error');
const backBtn = document.getElementById('back-btn');
const nextBtn = document.getElementById('next-btn');

// показать нужный шаг, остальные спрятать
function showStep(n) {
  steps.forEach(function (block) {
    block.hidden = Number(block.dataset.step) !== n;
  });

  // полоски сверху: всё до текущего шага синее
  stepperItems.forEach(function (item, i) {
    item.classList.toggle('stepper__item--active', i < n);
  });

  stepNumber.textContent = n;
  backBtn.hidden = n === 1;
  if (n === 4) {
    nextBtn.textContent = isEdit ? 'Сохранить изменения' : 'Опубликовать анкету';
    fillSummary();
  } else {
    nextBtn.textContent = 'Дальше';
  }
  hideError();
  window.scrollTo(0, 0);
}

function showError(text) {
  errorBox.textContent = text;
  errorBox.hidden = false;
}

function hideError() {
  errorBox.hidden = true;
}

// какой вариант выбран в группе кнопок (radio)
function getChecked(name) {
  const checked = document.querySelector('input[name="' + name + '"]:checked');
  return checked ? checked.value : '';
}

function setChecked(name, value) {
  if (value === null || value === undefined) return;
  const input = document.querySelector('input[name="' + name + '"][value="' + value + '"]');
  if (input) input.checked = true;
}

// ===== Вопросы про привычки: рисуем по данным с сервера, по разделам =====
async function loadQuestions() {
  const result = await api('/questions');
  const box = document.getElementById('questions');
  if (!result.ok) {
    box.innerHTML = '<p class="form-error">' + esc(errorText(result)) + '</p>';
    return;
  }
  questions = result.data;
  document.getElementById('total-questions').textContent = questions.length;

  // собираем вопросы по разделам (порядок разделов — как они впервые встречаются).
  // Имя поля q1, q2… остаётся по номеру вопроса на сервере, меняется только порядок показа
  const sections = [];
  questions.forEach(function (q, i) {
    let group = sections.find(function (g) { return g.name === q.section; });
    if (!group) {
      group = { name: q.section, items: [] };
      sections.push(group);
    }
    group.items.push(i);
  });

  let html = '';
  let number = 0;
  sections.forEach(function (group) {
    html += '<h3 class="question-section">' + esc(group.name) + '</h3>';
    group.items.forEach(function (i) {
      const q = questions[i];
      number++;
      let chips = '';
      q.answers.forEach(function (answer, j) {
        chips += `<label class="chip"><input type="radio" name="q${i + 1}" value="${j}"><span>${esc(answer)}</span></label>`;
      });
      html += `
        <fieldset class="question">
          <legend>${number}. ${esc(q.text)}</legend>
          <div class="chips-row">${chips}</div>
        </fieldset>`;
    });
  });
  box.innerHTML = html;

  box.querySelectorAll('input').forEach(function (input) {
    input.addEventListener('change', updateCounter);
  });
}

// сколько вопросов про привычки отвечено
function countAnswers() {
  let count = 0;
  for (let i = 1; i <= questions.length; i++) {
    if (getChecked('q' + i) !== '') {
      count++;
    }
  }
  return count;
}

function updateCounter() {
  document.getElementById('answered').textContent = countAnswers();
}

// склонение: 1 вопрос, 2 вопроса, 5 вопросов
function questionsWord(n) {
  if (n % 10 === 1 && n % 100 !== 11) return 'вопрос';
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return 'вопроса';
  return 'вопросов';
}

// итог на 4 шаге
function fillSummary() {
  const name = document.getElementById('name').value.trim();
  let tg = document.getElementById('telegram').value.trim();
  if (tg !== '' && tg[0] !== '@') {
    tg = '@' + tg;
  }

  document.getElementById('sum-name').textContent = name || '—';
  document.getElementById('sum-tg').textContent = tg || '—';
  document.getElementById('sum-gender').textContent = checkedLabel('gender') + ', ищешь: ' + checkedLabel('seek_gender').toLowerCase();
  document.getElementById('sum-habits').textContent = countAnswers() + ' из ' + questions.length + ' ответов';
  document.getElementById('sum-housing').textContent = checkedLabel('housing') + ', ' + checkedLabel('budget');
}

// текст выбранного варианта (то, что видно на кнопке)
function checkedLabel(name) {
  const checked = document.querySelector('input[name="' + name + '"]:checked');
  return checked ? checked.nextElementSibling.textContent : '—';
}

// подсказка «нужно войти», если пользователь не вошёл
document.getElementById('login-hint').hidden = !!getToken();

// проверка текущего шага. Если всё ок — возвращаем true
function checkStep() {
  if (step === 1) {
    const name = document.getElementById('name').value.trim();
    const tg = document.getElementById('telegram').value.trim();
    if (name === '' || tg === '') {
      showError('Заполни имя и Telegram, без них анкету не опубликовать.');
      return false;
    }
    if (getChecked('gender') === '' || getChecked('seek_gender') === '') {
      showError('Отметь, кто ты и кого ищешь в соседи.');
      return false;
    }
  }

  if (step === 2) {
    if (questions.length === 0) {
      showError('Вопросы не загрузились. Обнови страницу.');
      return false;
    }
    const left = questions.length - countAnswers();
    if (left > 0) {
      showError('Осталось ответить на ' + left + ' ' + questionsWord(left) + '.');
      return false;
    }
  }

  if (step === 3) {
    if (getChecked('housing') === '' || getChecked('budget') === '') {
      showError('Выбери, что ищешь, и бюджет.');
      return false;
    }
  }

  if (step === 4) {
    const agree1 = document.getElementById('agree1').checked;
    const agree2 = document.getElementById('agree2').checked;
    if (!agree1 || !agree2) {
      showError('Отметь оба пункта, чтобы опубликовать анкету.');
      return false;
    }
  }

  return true;
}

let createdId = null; // id анкеты, который вернул сервер

// собираем все ответы в объект, который поймёт сервер
function collectProfile() {
  const answers = [];
  for (let i = 1; i <= questions.length; i++) {
    answers.push(Number(getChecked('q' + i)));
  }
  return {
    name: document.getElementById('name').value.trim(),
    course: Number(getChecked('course')) || 1,
    telegram: document.getElementById('telegram').value.trim(),
    about: document.getElementById('about').value.trim(),
    gender: getChecked('gender'),
    seek_gender: getChecked('seek_gender'),
    university: document.getElementById('university').value.trim(),
    housing: getChecked('housing'),
    budget: getChecked('budget'),
    place: document.getElementById('area').value.trim(),
    when: getChecked('when'),
    answers: answers
  };
}

// ===== Фото =====
let photoFile = null;
const photoFileInput = document.getElementById('photo-file');
const photoPreview = document.getElementById('photo-preview');

photoFileInput.addEventListener('change', function () {
  const file = photoFileInput.files[0];
  if (!file) return;
  if (file.size > 8 * 1024 * 1024) {
    showError('Фото больше 8 МБ, выбери поменьше.');
    photoFileInput.value = '';
    return;
  }
  hideError();
  photoFile = file;
  // превью прямо в браузере, ещё до отправки на сервер
  photoPreview.innerHTML = '<img src="' + URL.createObjectURL(file) + '" alt="Фото">';
  document.getElementById('photo-pick-text').textContent = 'Другое фото';
  document.getElementById('photo-clear').hidden = false;
});

document.getElementById('photo-clear').addEventListener('click', function () {
  photoFile = null;
  photoFileInput.value = '';
  photoPreview.innerHTML = '<span>📷</span>';
  document.getElementById('photo-pick-text').textContent = 'Выбрать фото';
  document.getElementById('photo-clear').hidden = true;
});

// ===== Режим редактирования: заполняем форму тем, что уже есть на сервере =====
async function loadForEdit() {
  if (!getToken()) {
    window.location.href = 'login.html?next=' + encodeURIComponent('anketa.html?edit=1');
    return;
  }
  const me = await api('/me');
  if (!me.ok || me.data.profile_id === null) {
    window.location.href = 'anketa.html';  // анкеты нет — создаём новую
    return;
  }
  editId = me.data.profile_id;
  const result = await api('/profiles/' + editId);
  if (!result.ok) {
    showError(errorText(result));
    return;
  }
  const p = result.data.edit;

  document.title = 'Редактирование анкеты — Соседи';
  document.getElementById('form-title').textContent = 'Редактирование анкеты';
  document.getElementById('name').value = p.name;
  document.getElementById('telegram').value = p.telegram;
  document.getElementById('about').value = p.about || '';
  document.getElementById('university').value = p.university || '';
  document.getElementById('area').value = p.place === 'Район не указан' ? '' : p.place;
  setChecked('gender', p.gender);
  setChecked('seek_gender', p.seek_gender);
  setChecked('course', p.course >= 5 ? 5 : p.course);
  setChecked('housing', p.housing);
  setChecked('budget', p.budget);
  setChecked('when', p.when);
  p.answers.forEach(function (a, i) {
    setChecked('q' + (i + 1), a);
  });
  updateCounter();
  document.getElementById('agree1').checked = true;
  document.getElementById('agree2').checked = true;

  if (result.data.photo) {
    photoPreview.innerHTML = '<img src="' + result.data.photo + '" alt="Фото">';
    document.getElementById('photo-pick-text').textContent = 'Сменить фото';
  }

  // после обновления появились новые вопросы — подскажем, что нужно ответить
  if (p.gender === null || p.answers.indexOf(null) !== -1) {
    const note = document.getElementById('edit-note');
    note.hidden = false;
  }
}

nextBtn.addEventListener('click', async function () {
  if (!checkStep()) {
    return;
  }

  if (step < 4) {
    step++;
    showStep(step);
    return;
  }

  // последний шаг: отправляем анкету на сервер
  if (!getToken()) {
    showError('Сначала войди в аккаунт — без этого сервер не сохранит анкету.');
    return;
  }

  nextBtn.disabled = true;
  const result = isEdit
    ? await api('/profiles/' + editId, { method: 'PUT', body: collectProfile() })
    : await api('/profiles', { method: 'POST', body: collectProfile() });
  nextBtn.disabled = false;

  if (!result.ok) {
    showError(errorText(result));
    return;
  }

  createdId = result.data.id;

  // анкета сохранена — теперь отправляем фото, если его выбрали
  if (photoFile) {
    const photoResult = await apiUpload('/profiles/' + createdId + '/photo', photoFile);
    if (!photoResult.ok) {
      document.getElementById('done-photo-error').textContent =
        'Анкета сохранена, но фото не загрузилось: ' + errorText(photoResult) + ' Его можно добавить на странице анкеты.';
      document.getElementById('done-photo-error').hidden = false;
    }
  }
  document.getElementById('done-link').href = 'profile.html?id=' + createdId;

  if (isEdit) {
    document.getElementById('done-title').textContent = 'Изменения сохранены';
    document.getElementById('done-text').textContent = 'Анкета обновлена. Фото, отметки «Интересно» и подписка остались на месте.';
  }

  document.getElementById('form-block').hidden = true;
  document.getElementById('done-block').hidden = false;
  window.scrollTo(0, 0);
});

backBtn.addEventListener('click', function () {
  step--;
  showStep(step);
});

// удаление анкеты, сначала спрашиваем подтверждение
document.getElementById('delete-btn').addEventListener('click', function () {
  document.getElementById('confirm-block').hidden = false;
});

document.getElementById('confirm-no').addEventListener('click', function () {
  document.getElementById('confirm-block').hidden = true;
});

document.getElementById('confirm-yes').addEventListener('click', async function () {
  const result = await api('/profiles/' + createdId, { method: 'DELETE' });
  if (!result.ok) {
    document.querySelector('#confirm-block p').textContent = errorText(result);
    return;
  }
  document.getElementById('done-ok').hidden = true;
  document.getElementById('done-deleted').hidden = false;
});

// сначала вопросы, потом (если правим) — заполняем форму
loadQuestions().then(async function () {
  if (isEdit) {
    loadForEdit();
    return;
  }
  // анкета уже есть — открываем её на редактирование, а не создаём вторую
  if (getToken()) {
    const me = await api('/me');
    if (me.ok && me.data.profile_id !== null) {
      window.location.href = 'anketa.html?edit=1';
    }
  }
});
