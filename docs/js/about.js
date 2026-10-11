// Вопросы-ответы: когда открываешь один вопрос, остальные закрываются

const questions = document.querySelectorAll('.faq details');

questions.forEach(function (item) {
  item.addEventListener('toggle', function () {
    if (item.open) {
      questions.forEach(function (other) {
        if (other !== item) {
          other.open = false;
        }
      });
    }
  });
});
