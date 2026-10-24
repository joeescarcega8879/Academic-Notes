// IA asistida: abrir el panel, contar las aprobadas y esperar a que termine una generación.
(function () {
  document.querySelectorAll('[data-ai-open]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (typeof openModal === 'function') openModal(button.dataset.aiOpen);
    });
  });

  // Pantalla de revisión: el contador y el botón siguen a las casillas.
  var review = document.querySelector('[data-ai-review]');
  if (review) {
    var boxes = Array.prototype.slice.call(review.querySelectorAll('[data-ai-approve]'));
    var all = review.querySelector('[data-ai-all]');
    var apply = review.querySelector('[data-ai-apply]');
    var refresh = function () {
      var n = boxes.filter(function (box) { return box.checked; }).length;
      var label = n + (n === 1 ? ' aprobada' : ' aprobadas');
      review.querySelectorAll('[data-ai-approved-text]').forEach(function (el) { el.textContent = label; });
      review.querySelectorAll('[data-ai-approved-chip]').forEach(function (el) { el.textContent = label; });
      if (apply) {
        apply.disabled = n === 0;
        apply.textContent = 'Aprobar ' + n + ' y agregar al quiz';
      }
      if (all) all.checked = boxes.length > 0 && n === boxes.length;
    };
    boxes.forEach(function (box) { box.addEventListener('change', refresh); });
    if (all) {
      all.addEventListener('change', function () {
        boxes.forEach(function (box) { box.checked = all.checked; });
        refresh();
      });
    }
    refresh();
  }

  // Mientras algo se genera en segundo plano, preguntar si ya terminó y recargar.
  var waiting = document.querySelector('[data-ai-poll]');
  if (waiting && window.fetch) {
    var url = waiting.dataset.aiPoll;
    var timer = setInterval(function () {
      fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (response) { return response.ok ? response.json() : { busy: true }; })
        .then(function (data) { if (!data.busy) { clearInterval(timer); window.location.reload(); } })
        .catch(function () { /* sin red un momento: se vuelve a preguntar */ });
    }, 2500);
  }
})();
