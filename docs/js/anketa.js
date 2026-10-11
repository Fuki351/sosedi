// Анкета из 4 шагов: показываем один шаг, проверяем поля, идём дальше

let step = 1;

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
  nextBtn.textContent = n === 4 ? 'Опубликовать анкету' : 'Дальше';
  hideError();

  if (n === 4) {
    fillSummary();
  }

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

// сколько из 9 вопросов про привычки отвечено
function countAnswers() {
  let count = 0;
  for (let i = 1; i <= 9; i++) {
    if (getChecked('q' + i) !== '') {
      count++;
    }
  }
  return count;
}

// склонение: 1 вопрос, 2 вопроса, 5 вопросов
function questionsWord(n) {
  if (n === 1) return 'вопрос';
  if (n >= 2 && n <= 4) return 'вопроса';
  return 'вопросов';
}

// обновляем счётчик, когда что-то выбрали
document.querySelectorAll('input[name^="q"]').forEach(function (input) {
  input.addEventListener('change', function () {
    document.getElementById('answered').textContent = countAnswers();
  });
});

// итог на 4 шаге
function fillSummary() {
  const name = document.getElementById('name').value.trim();
  let tg = document.getElementById('telegram').value.trim();
  if (tg !== '' && tg[0] !== '@') {
    tg = '@' + tg;
  }

  document.getElementById('sum-name').textContent = name || '—';
  document.getElementById('sum-tg').textContent = tg || '—';
  document.getElementById('sum-habits').textContent = countAnswers() + ' из 9 ответов';
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
  }

  if (step === 2) {
    const left = 9 - countAnswers();
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
  for (let i = 1; i <= 9; i++) {
    answers.push(Number(getChecked('q' + i)));
  }
  return {
    name: document.getElementById('name').value.trim(),
    course: Number(getChecked('course')) || 1,
    telegram: document.getElementById('telegram').value.trim(),
    about: document.getElementById('about').value.trim(),
    housing: getChecked('housing'),
    budget: getChecked('budget'),
    place: document.getElementById('area').value.trim(),
    when: checkedLabel('when') === '—' ? '' : checkedLabel('when'),
    answers: answers
  };
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
  const result = await api('/profiles', { method: 'POST', body: collectProfile() });
  nextBtn.disabled = false;

  if (!result.ok) {
    showError(errorText(result));
    return;
  }

  createdId = result.data.id;
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
