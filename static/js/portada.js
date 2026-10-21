// Interacciones de la portada: la libreta de ejemplo y la pregunta del quiz.
// Todo es demostración en el navegador: no se envía ni se guarda nada.
(function () {
  'use strict';

  var PRESETS = [[0.5, 0.3, 0.2], [0.4, 0.4, 0.2], [0.3, 0.3, 0.4]];
  var weights = PRESETS[0];
  var body = document.getElementById('sheet-body');

  function round1(x) { return Math.round((x + 1e-9) * 10) / 10; }
  function clamp(v) { return isNaN(v) ? 0 : Math.min(10, Math.max(0, v)); }
  function state(avg) {
    if (avg >= 8) return { cls: 'ok', text: 'Muy bien' };
    if (avg >= 6) return { cls: 'warn', text: 'Aprobando' };
    return { cls: 'bad', text: 'En riesgo' };
  }

  if (body) {
    var rows = Array.prototype.slice.call(body.rows);

    var recalc = function (changed) {
      var total = 0;
      var risk = 0;
      rows.forEach(function (tr) {
        var inputs = tr.querySelectorAll('input');
        var avg = 0;
        for (var i = 0; i < 3; i++) avg += clamp(parseFloat(inputs[i].value)) * weights[i];
        avg = round1(avg);
        total += avg;
        var s = state(avg);
        if (s.cls === 'bad') risk++;
        var strong = tr.querySelector('.avg strong');
        var chip = tr.querySelector('.avg .chip');
        strong.textContent = avg.toFixed(1);
        chip.className = 'chip ' + s.cls;
        chip.textContent = s.text;
        if (changed === tr) {
          strong.classList.add('pop');
          setTimeout(function () { strong.classList.remove('pop'); }, 220);
        }
      });
      document.getElementById('group-avg').textContent = round1(total / rows.length).toFixed(1);
      var riskChip = document.getElementById('risk-count');
      riskChip.className = 'chip ' + (risk === 0 ? 'ok' : 'bad');
      riskChip.textContent = risk === 0 ? 'Nadie en riesgo' : risk + (risk === 1 ? ' alumno en riesgo' : ' alumnos en riesgo');
    };

    body.addEventListener('input', function (e) {
      var input = e.target;
      if (input.tagName !== 'INPUT') return;
      var v = parseFloat(input.value);
      if (!isNaN(v) && v > 10) input.value = 10;
      if (!isNaN(v) && v < 0) input.value = 0;
      recalc(input.closest('tr'));
    });

    var presetButtons = document.querySelectorAll('[data-preset]');
    presetButtons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        weights = PRESETS[Number(btn.dataset.preset)];
        presetButtons.forEach(function (b) { b.setAttribute('aria-pressed', String(b === btn)); });
        document.querySelectorAll('[data-w]').forEach(function (el) {
          el.textContent = Math.round(weights[Number(el.dataset.w)] * 100) + '%';
        });
        recalc();
      });
    });

    recalc();
  }

  var quiz = document.querySelector('[data-quiz]');
  if (quiz) {
    var result = quiz.querySelector('.quiz-res');
    var options = quiz.querySelectorAll('.opt');
    options.forEach(function (opt) {
      opt.addEventListener('click', function () {
        var correct = opt.dataset.ok === '1';
        options.forEach(function (o) {
          if (o.dataset.ok === '1') o.classList.add('right');
          o.disabled = true;
        });
        if (!correct) opt.classList.add('wrong');
        result.textContent = correct
          ? 'Correcta. Calificada al instante.'
          : 'Incorrecta: la respuesta era 12. Calificada al instante.';
      });
    });
  }
})();
