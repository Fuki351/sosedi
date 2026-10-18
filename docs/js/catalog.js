// Каталог анкет: загружаем список с сервера, фильтры, кнопка «Показать ещё»

let people = []; // то, что пришло с сервера
let shown = 12;   // сколько карточек показываем сейчас

const cardsList = document.getElementById('cards');
const countText = document.getElementById('count');
const moreBtn = document.getElementById('more-btn');
const emptyBlock = document.getElementById('empty');
const loadError = document.getElementById('load-error');

// если не вошли — подсказка, что процент совместимости появится после входа
document.getElementById('login-hint').hidden = !!getToken();

function getChecked(name) {
  return document.querySelector('input[name="' + name + '"]:checked').value;
}

// отмеченные галочки курса: "1,2,5,6"
function getCourses() {
  const values = [];
  document.querySelectorAll('input[name="course"]:checked').forEach(function (input) {
    values.push(input.value);
  });
  return values.join(',');
}

function isOn(id) {
  return document.getElementById(id).checked;
}

// цвет процента: от 70 зелёный, от 55 синий, ниже серый
function matchClass(match) {
  if (match >= 70) return 'match-badge--high';
  if (match >= 55) return 'match-badge--mid';
  return 'match-badge--low';
}

// 1 анкета, 2 анкеты, 5 анкет
function word(n) {
  if (n % 10 === 1 && n % 100 !== 11) return 'анкета';
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return 'анкеты';
  return 'анкет';
}

// просим у сервера анкеты. Фильтрует тоже сервер — передаём фильтры в адресе запроса
async function loadPeople() {
  const params = new URLSearchParams({
    sort: document.getElementById('sort').value,
    gender: getChecked('gender'),
    housing: getChecked('housing'),
    budget: getChecked('budget'),
    university: document.getElementById('f-university').value.trim(),
    place: document.getElementById('f-place').value.trim(),
    course: getCourses(),
    when: getChecked('when'),
    sleep: getChecked('sleep'),
    guests: isOn('f-guests') ? 'rare' : 'any',
    tidy: isOn('f-tidy'),
    quiet: isOn('f-quiet'),
    with_photo: isOn('f-photo'),
    no_smoke: isOn('no-smoke'),
    no_pets: isOn('no-pets'),
    min_match: document.getElementById('min-match').value
  });

  countText.textContent = 'Загружаем анкеты…';
  const result = await api('/profiles?' + params.toString());

  if (!result.ok) {
    people = [];
    loadError.textContent = errorText(result);
    loadError.hidden = false;
    countText.textContent = '';
    render();
    return;
  }

  loadError.hidden = true;
  people = result.data;
  render();
}

function render() {
  if (loadError.hidden) {
    countText.textContent = 'Нашли ' + people.length + ' ' + word(people.length);
  }
  cardsList.innerHTML = '';

  people.slice(0, shown).forEach(function (p) {
    let tagsHtml = '';
    p.tags.forEach(function (tag) {
      tagsHtml += '<li>' + esc(tag) + '</li>';
    });

    // процент показываем, только если сервер его посчитал (мы вошли и есть анкета)
    let matchHtml = '';
    if (p.match !== null) {
      matchHtml = `<span class="match-badge ${matchClass(p.match)}">${p.match}%</span>`;
    }

    // сверху фото; если фото нет — цветная заглушка с буквой
    const cover = p.photo
      ? `<img src="${p.photo}" alt="${esc(p.name)}" loading="lazy">`
      : `<span class="person-card__letter" style="background:${avatarColor(p.id)}">${esc(p.name[0])}</span>`;
    const premiumHtml = p.premium ? '<span class="plus-badge">★ Соседи+</span>'
      : (p.demo ? '<span class="demo-badge">Пример анкеты</span>' : '');

    cardsList.innerHTML += `
      <li class="person-card${p.premium ? ' person-card--plus' : ''}">
        <a href="profile.html?id=${p.id}" class="person-card__cover">
          ${cover}
          ${premiumHtml}
          ${matchHtml}
        </a>
        <div class="person-card__body">
          <p class="person__name">${esc(p.name)}, ${p.course} курс</p>
          <p class="person__info">${esc(p.housing_text)}</p>
          ${p.university ? `<p class="person-card__uni">🎓 ${esc(p.university)}</p>` : ''}
          <p class="person-card__place">📍 ${esc(p.place)}</p>
          <ul class="tags">${tagsHtml}</ul>
          <a href="profile.html?id=${p.id}" class="person-card__link">Открыть анкету</a>
        </div>
      </li>
    `;
  });

  emptyBlock.hidden = people.length > 0 || !loadError.hidden;
  moreBtn.hidden = people.length <= shown;
}

// при любом изменении фильтров заново спрашиваем сервер
function reload() {
  shown = 12;
  loadPeople();
}

document.querySelectorAll('#filters input[type="radio"], #filters input[type="checkbox"], #sort').forEach(function (input) {
  input.addEventListener('change', reload);
});

// текстовые поля: ждём, пока человек перестанет печатать
let typingTimer = null;
['f-university', 'f-place'].forEach(function (id) {
  document.getElementById(id).addEventListener('input', function () {
    clearTimeout(typingTimer);
    typingTimer = setTimeout(reload, 400);
  });
});

const minMatch = document.getElementById('min-match');
minMatch.addEventListener('input', function () {
  document.getElementById('min-match-text').textContent = minMatch.value;
});
minMatch.addEventListener('change', reload);

moreBtn.addEventListener('click', function () {
  shown += 12;
  render();
});

function resetFilters() {
  ['housing:all', 'budget:any', 'gender:any', 'when:any', 'sleep:any'].forEach(function (pair) {
    const parts = pair.split(':');
    document.querySelector('input[name="' + parts[0] + '"][value="' + parts[1] + '"]').checked = true;
  });
  document.querySelectorAll('#filters input[type="checkbox"]').forEach(function (input) {
    input.checked = false;
  });
  document.getElementById('f-university').value = '';
  document.getElementById('f-place').value = '';
  document.getElementById('sort').value = 'match';
  minMatch.value = 0;
  document.getElementById('min-match-text').textContent = '0';
  reload();
}

document.getElementById('reset-btn').addEventListener('click', resetFilters);
document.getElementById('empty-reset').addEventListener('click', resetFilters);

// фильтры на телефоне
const filters = document.getElementById('filters');
const filtersToggle = document.getElementById('filters-toggle');

filtersToggle.addEventListener('click', function () {
  filters.classList.toggle('filters--open');
  if (filters.classList.contains('filters--open')) {
    filtersToggle.textContent = 'Скрыть фильтры';
  } else {
    filtersToggle.textContent = 'Фильтры';
  }
});

// если вошли — подставляем «кого ищу» из своей анкеты; фильтр по % — только когда есть своя анкета
async function start() {
  document.getElementById('match-filter').hidden = true;
  if (getToken()) {
    const me = await api('/me');
    if (me.ok && me.data.profile_id !== null) {
      document.getElementById('match-filter').hidden = false;
      if (me.data.profile_incomplete) {
        const hint = document.getElementById('login-hint');
        hint.innerHTML = 'В анкете появились новые вопросы. <a href="anketa.html?edit=1">Дополни анкету</a>, чтобы тебя находили через фильтры.';
        hint.hidden = false;
      }
    }
  }
  loadPeople();
}

start();
