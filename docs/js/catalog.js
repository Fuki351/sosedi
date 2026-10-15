// Каталог анкет: загружаем список с сервера, фильтры, кнопка «Показать ещё»

let people = []; // то, что пришло с сервера
let shown = 6;   // сколько карточек показываем сейчас

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
    housing: getChecked('housing'),
    budget: getChecked('budget'),
    no_smoke: document.getElementById('no-smoke').checked,
    no_pets: document.getElementById('no-pets').checked
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
    const premiumHtml = p.premium ? '<span class="plus-badge">★ Соседи+</span>' : '';

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
document.querySelectorAll('#filters input').forEach(function (input) {
  input.addEventListener('change', function () {
    shown = 6;
    loadPeople();
  });
});

moreBtn.addEventListener('click', function () {
  shown += 3;
  render();
});

function resetFilters() {
  document.querySelector('input[name="housing"][value="all"]').checked = true;
  document.querySelector('input[name="budget"][value="any"]').checked = true;
  document.getElementById('no-smoke').checked = false;
  document.getElementById('no-pets').checked = false;
  shown = 6;
  loadPeople();
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

loadPeople();
