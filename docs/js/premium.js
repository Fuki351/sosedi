// Страница подписки «Соседи+»: тарифы и демо-оплата

const plansBox = document.getElementById('plans');
const plusError = document.getElementById('plus-error');
const modal = document.getElementById('pay-modal');
let chosenPlan = null;
let plans = [];
let paymentMode = 'demo';

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
  paymentMode = info.payment_mode;
  const note = document.getElementById('pay-note');
  const confirmBtn = document.getElementById('pay-confirm');
  if (paymentMode === 'yookassa') {
    note.innerHTML = 'Оплата через <b>ЮKassa</b>: откроется страница оплаты, после неё вернёшься сюда.' +
      (info.test_mode ? ' Сейчас магазин в <b>тестовом режиме</b> — плати тестовой картой 5555 5555 5555 4477, срок любой будущий, CVC любой.' : '');
    confirmBtn.textContent = 'Перейти к оплате';
  } else {
    note.innerHTML = 'Это <b>демо-режим</b>: деньги не списываются, подписка включится сразу.';
    confirmBtn.textContent = 'Оплатить (демо)';
  }
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
  if (result.ok && result.data.mode === 'yookassa') {
    // уходим на страницу оплаты ЮKassa, оттуда вернёмся с ?payment=номер
    window.location.href = result.data.confirmation_url;
    return;
  }
  btn.disabled = false;
  modal.hidden = true;
  if (!result.ok) {
    plusError.textContent = errorText(result);
    plusError.hidden = false;
    return;
  }
  // вернулись со страницы ЮKassa: спрашиваем сервер, прошла ли оплата.
// Подтверждение может прийти не сразу, поэтому проверяем несколько раз
async function checkReturnedPayment() {
  const paymentId = new URLSearchParams(window.location.search).get('payment');
  if (!paymentId || !getToken()) return;
  const checking = document.getElementById('pay-checking');
  const failed = document.getElementById('pay-failed');
  checking.hidden = false;
  for (let i = 0; i < 10; i++) {
    const result = await api('/premium/payments/' + paymentId);
    if (result.ok && result.data.status === 'succeeded') {
      checking.hidden = true;
      history.replaceState(null, '', 'premium.html');
      loadPlans();
      return;
    }
    if (result.ok && result.data.status === 'canceled') {
      checking.hidden = true;
      failed.textContent = 'Оплата не прошла или была отменена. Деньги не списаны — можно попробовать ещё раз.';
      failed.hidden = false;
      return;
    }
    await new Promise(function (resolve) { setTimeout(resolve, 2000); });
  }
  checking.hidden = true;
  failed.textContent = 'Оплата ещё обрабатывается. Обнови страницу через минуту — подписка включится автоматически.';
  failed.hidden = false;
}

loadPlans();
checkReturnedPayment();
  window.scrollTo(0, 0);
});

// вернулись со страницы ЮKassa: спрашиваем сервер, прошла ли оплата.
// Подтверждение может прийти не сразу, поэтому проверяем несколько раз
async function checkReturnedPayment() {
  const paymentId = new URLSearchParams(window.location.search).get('payment');
  if (!paymentId || !getToken()) return;
  const checking = document.getElementById('pay-checking');
  const failed = document.getElementById('pay-failed');
  checking.hidden = false;
  for (let i = 0; i < 10; i++) {
    const result = await api('/premium/payments/' + paymentId);
    if (result.ok && result.data.status === 'succeeded') {
      checking.hidden = true;
      history.replaceState(null, '', 'premium.html');
      loadPlans();
      return;
    }
    if (result.ok && result.data.status === 'canceled') {
      checking.hidden = true;
      failed.textContent = 'Оплата не прошла или была отменена. Деньги не списаны — можно попробовать ещё раз.';
      failed.hidden = false;
      return;
    }
    await new Promise(function (resolve) { setTimeout(resolve, 2000); });
  }
  checking.hidden = true;
  failed.textContent = 'Оплата ещё обрабатывается. Обнови страницу через минуту — подписка включится автоматически.';
  failed.hidden = false;
}

loadPlans();
checkReturnedPayment();
