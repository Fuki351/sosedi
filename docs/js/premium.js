// Страница подписки «Соседи+»: тарифы и демо-оплата

const plansBox = document.getElementById('plans');
const plusError = document.getElementById('plus-error');
const modal = document.getElementById('pay-modal');
let chosenPlan = null;
let plans = [];

function rub(n) {
  return n.toLocaleString('ru-RU') + ' ₽';
}

function untilText(until) {
  // "2026-11-14 20:18" -> "14.11.2026"
  const d = until.slice(0, 10).split('-');
  return d[2] + '.' + d[1] + '.' + d[0];
}

async function loadPlans() {
  const result = await api('/premium');
  if (!result.ok) {
    plusError.textContent = errorText(result);
    plusError.hidden = false;
    return;
  }
  const info = result.data;
  plans = info.plans;
  document.getElementById('free-limit').textContent = info.free_daily_interests;

  const active = document.getElementById('plus-active');
  if (info.active) {
    active.textContent = '★ Подписка активна до ' + untilText(info.until) + '. Можно продлить заранее — дни добавятся.';
    active.hidden = false;
  }

  plansBox.innerHTML = '';
  plans.forEach(function (plan) {
    const perMonth = Math.round(plan.price / (plan.days / 30));
    const best = plan.days > 30;
    plansBox.innerHTML += `
      <div class="plan${best ? ' plan--best' : ''}">
        ${best ? '<span class="plan__flag">Выгоднее на 25%</span>' : ''}
        <p class="plan__title">${esc(plan.title)}</p>
        <p class="plan__price">${rub(plan.price)}</p>
        <p class="plan__note">${best ? rub(perMonth) + ' в месяц' : 'на 30 дней'}</p>
        <button type="button" class="btn ${best ? 'btn--gold' : 'btn--light'}" data-plan="${plan.id}">
          ${info.active ? 'Продлить' : 'Подключить'}
        </button>
      </div>`;
  });

  plansBox.querySelectorAll('button[data-plan]').forEach(function (btn) {
    btn.addEventListener('click', function () { openPay(btn.dataset.plan); });
  });
}

function openPay(planId) {
  if (!getToken()) {
    window.location.href = 'login.html?next=premium.html';
    return;
  }
  chosenPlan = plans.find(function (p) { return p.id === planId; });
  document.getElementById('pay-sum').textContent = 'Соседи+ · ' + chosenPlan.title + ' — ' + rub(chosenPlan.price);
  modal.hidden = false;
}

document.getElementById('pay-cancel').addEventListener('click', function () {
  modal.hidden = true;
});

document.getElementById('pay-confirm').addEventListener('click', async function () {
  const btn = document.getElementById('pay-confirm');
  btn.disabled = true;
  const result = await api('/premium/checkout', { method: 'POST', body: { plan: chosenPlan.id } });
  btn.disabled = false;
  modal.hidden = true;
  if (!result.ok) {
    plusError.textContent = errorText(result);
    plusError.hidden = false;
    return;
  }
  loadPlans();
  window.scrollTo(0, 0);
});

loadPlans();
