(function () {
  'use strict';

  // Mientras Celery lee los archivos del lote, preguntar si ya terminó y recargar la lista.
  var waiting = document.querySelector('[data-batch-poll]');
  if (!waiting || !window.fetch) return;
  var url = waiting.dataset.batchPoll;
  var timer = setInterval(function () {
    fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (response) { return response.ok ? response.json() : { busy: true }; })
      .then(function (data) { if (!data.busy) { clearInterval(timer); window.location.reload(); } })
      .catch(function () { /* sin red un momento: se vuelve a preguntar */ });
  }, 2500);
})();
