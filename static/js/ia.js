// IA asistida: abrir el panel, contar las aprobadas y esperar a que termine una generación.
(function () {
  document.querySelectorAll('[data-ai-open]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (typeof openModal === 'function') openModal(button.dataset.aiOpen);
    });
  });

  // Panel de preguntas desde el temario: un examen admite más preguntas y más tipos que un quiz.
  document.querySelectorAll('[data-ai-kind]').forEach(function (group) {
    var modal = group.closest('form');
    var refreshKind = function () {
      var exam = modal.querySelector('input[name=kind]:checked').value === 'exam';
      modal.querySelectorAll('[data-ai-exam-only]').forEach(function (el) {
        el.hidden = !exam;
        if (el.tagName === 'OPTION') {
          el.disabled = !exam;
          if (!exam && el.selected) el.parentNode.value = '10';
        } else {
          el.querySelectorAll('input').forEach(function (input) { input.disabled = !exam; });
        }
      });
      modal.querySelectorAll('[data-ai-quiz-only]').forEach(function (el) {
        el.hidden = exam;
        el.querySelectorAll('input').forEach(function (input) { input.disabled = exam; });
      });
    };
    group.addEventListener('change', refreshKind);
    refreshKind();
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
        apply.textContent = 'Aprobar ' + n + ' y agregar al ' + (apply.dataset.aiNoun || 'quiz');
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

  // Edición de una tarea: «+ Agregar criterio» copia la última fila en blanco.
  var addCriterion = document.querySelector('[data-ai-add-criterion]');
  if (addCriterion) {
    addCriterion.addEventListener('click', function () {
      var box = document.querySelector('[data-ai-criteria]');
      var row = box.lastElementChild.cloneNode(true);
      row.querySelectorAll('input').forEach(function (input) { input.value = ''; });
      box.appendChild(row);
      row.querySelector('input').focus();
    });
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
