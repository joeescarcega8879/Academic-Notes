/* Rúbricas: el editor de la cuadrícula (agregar y quitar criterios y niveles) y el total en vivo al calificar. */
(function () {
  'use strict';

  function number(text) {
    var value = parseFloat(String(text).replace(',', '.'));
    return isFinite(value) ? value : 0;
  }

  function show(value) {
    return String(Math.round(value * 100) / 100);
  }

  // ── Calificar: el total se calcula al elegir cada nivel (el servidor lo vuelve a calcular al guardar) ──
  var grade = document.getElementById('rubric-grade');
  if (grade) {
    var maxPoints = number(grade.dataset.maxPoints);
    var activityMax = number(grade.dataset.activityMax);
    var criteriaCount = parseInt(grade.dataset.criteria, 10) || 0;
    var penalty = number(grade.dataset.penalty);  // % por entrega tardía; 0 si no aplica
    var waive = grade.querySelector('[name=waive]');

    var refreshGrade = function () {
      var picked = grade.querySelectorAll('input[type=radio]:checked');
      var total = 0;
      picked.forEach(function (radio) { total += number(radio.dataset.points); });
      document.getElementById('grade-points').textContent = show(total) + ' / ' + show(maxPoints);
      document.getElementById('grade-count').textContent = picked.length + ' de ' + criteriaCount + ' criterios';
      var score = document.getElementById('grade-score');
      var done = picked.length === criteriaCount && maxPoints > 0;
      var base = done ? Math.round(total / maxPoints * activityMax * 100) / 100 : 0;
      score.textContent = done ? show(base) : '—';
      var note = document.getElementById('grade-penalty');
      if (note) {
        var applies = done && penalty > 0 && !(waive && waive.checked);
        note.textContent = applies ? 'Con ' + show(penalty) + ' % de penalización por entrega tardía: ' + show(base * (1 - penalty / 100)) : '';
      }
    };
    grade.addEventListener('change', refreshGrade);
    refreshGrade();
  }

  // ── Formulario de la actividad: aviso cuando la rúbrica y la actividad valen distinto ──
  var select = document.getElementById('id_rubric');
  var pointsData = document.getElementById('rubric-points');
  var maxInput = document.getElementById('id_max_score');
  if (select && pointsData && maxInput) {
    var values = JSON.parse(pointsData.textContent);
    var note = document.createElement('div');
    note.className = 'text-sm text-muted';
    note.setAttribute('aria-live', 'polite');
    note.style.marginTop = '6px';
    select.parentNode.appendChild(note);

    var refreshNote = function () {
      var rubricMax = values[select.value];
      note.textContent = '';
      if (rubricMax === undefined) return;
      var activityMax = number(maxInput.value);
      if (rubricMax === activityMax) {
        note.textContent = 'La rúbrica y la actividad valen lo mismo (' + show(rubricMax) + ' puntos).';
        return;
      }
      note.textContent = 'La rúbrica vale ' + show(rubricMax) + ' puntos y la actividad ' + show(activityMax) +
        ': la calificación se escala (' + show(rubricMax * 0.85) + ' de ' + show(rubricMax) + ' en la rúbrica serían ' +
        show(activityMax * 0.85) + ' de ' + show(activityMax) + '). ';
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-ghost btn-sm';
      button.textContent = 'Usar ' + show(rubricMax) + ' puntos';
      button.addEventListener('click', function () { maxInput.value = show(rubricMax); refreshNote(); });
      note.appendChild(button);
    };
    select.addEventListener('change', refreshNote);
    maxInput.addEventListener('input', refreshNote);
    refreshNote();
  }

  // ── Editor ──────────────────────────────────────────────────────────────
  var form = document.getElementById('rubric-form');
  if (!form) return;
  var board = document.getElementById('rub-edit');
  var head = document.getElementById('rub-head');
  var minLevels = parseInt(form.dataset.minLevels, 10);
  var maxLevels = parseInt(form.dataset.maxLevels, 10);
  var maxCriteria = parseInt(form.dataset.maxCriteria, 10);

  function criteria() { return Array.prototype.slice.call(board.querySelectorAll('[data-criterion]')); }
  function levels() { return Array.prototype.slice.call(head.querySelectorAll('[data-level]')); }

  function el(tag, attrs, html) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (html) node.innerHTML = html;
    return node;
  }

  // Los nombres de los campos van por posición (c0_name, c0_l1_points…): se reescriben tras cada cambio.
  function renumber() {
    var levelBoxes = levels();
    levelBoxes.forEach(function (box, j) {
      var input = box.querySelector('input');
      input.name = 'level_' + j;
      input.setAttribute('aria-label', 'Nombre del nivel ' + (j + 1));
    });
    criteria().forEach(function (row, i) {
      var name = row.querySelector('.rub-cn input');
      name.name = 'c' + i + '_name';
      name.setAttribute('aria-label', 'Nombre del criterio ' + (i + 1));
      row.querySelectorAll('[data-cell]').forEach(function (cell, j) {
        var points = cell.querySelector('.rub-points');
        points.name = 'c' + i + '_l' + j + '_points';
        points.id = points.name;
        cell.querySelector('label').setAttribute('for', points.id);
        cell.querySelector('textarea').name = 'c' + i + '_l' + j + '_text';
        var label = cell.querySelector('[data-level-label]');
        if (label && levelBoxes[j]) label.textContent = levelBoxes[j].querySelector('input').value;
      });
    });
    form.elements.levels.value = levelBoxes.length;
    form.elements.criteria.value = criteria().length;
    board.style.setProperty('--cols', levelBoxes.length);
    document.getElementById('add-level').disabled = levelBoxes.length >= maxLevels;
    document.getElementById('add-criterion').disabled = criteria().length >= maxCriteria;
    board.querySelectorAll('[data-remove-level]').forEach(function (button) { button.hidden = levelBoxes.length <= minLevels; });
    board.querySelectorAll('[data-remove-criterion]').forEach(function (button) { button.hidden = criteria().length <= 1; });
    total();
  }

  // La rúbrica vale la suma de lo más alto de cada criterio.
  function total() {
    var sum = 0;
    criteria().forEach(function (row) {
      var top = 0;
      row.querySelectorAll('.rub-points').forEach(function (input) { top = Math.max(top, number(input.value)); });
      sum += top;
    });
    document.getElementById('rub-total').textContent = show(sum);
    document.getElementById('rub-count').textContent = '· ' + criteria().length + ' criterio' + (criteria().length === 1 ? '' : 's');
  }

  function newCell(levelName, points) {
    var cell = el('div', { 'class': 'rub-lv', 'data-cell': '' });
    cell.appendChild(el('span', { 'class': 'rub-lvn', 'data-level-label': '' }));
    cell.lastChild.textContent = levelName;
    cell.appendChild(el('label', { 'class': 'sr-only' }, 'Puntos'));
    cell.appendChild(el('input', { 'class': 'input rub-points', type: 'text', inputmode: 'decimal', maxlength: '7', value: points }));
    cell.appendChild(el('textarea', { 'class': 'input', rows: '3', maxlength: '1000', placeholder: 'Qué se espera en este nivel', 'aria-label': 'Descripción' }));
    return cell;
  }

  document.getElementById('add-criterion').addEventListener('click', function () {
    var row = el('div', { 'class': 'rub-crit', 'data-criterion': '' });
    var title = el('div', { 'class': 'rub-cn' });
    title.appendChild(el('input', { 'class': 'input', type: 'text', maxlength: '150', placeholder: 'Nombre del criterio' }));
    title.appendChild(el('button', { type: 'button', 'class': 'rub-rm', 'data-remove-criterion': '' }, 'Quitar criterio'));
    row.appendChild(title);
    var defaults = [4, 3, 2, 0];
    levels().forEach(function (box, j) {
      row.appendChild(newCell(box.querySelector('input').value, String(j < defaults.length ? defaults[j] : 0)));
    });
    board.appendChild(row);
    renumber();
    title.querySelector('input').focus();
  });

  document.getElementById('add-level').addEventListener('click', function () {
    var box = el('div', { 'data-level': '' });
    box.appendChild(el('input', { 'class': 'input', type: 'text', maxlength: '60', value: 'Nivel ' + (levels().length + 1) }));
    box.appendChild(el('button', { type: 'button', 'class': 'rub-rm', 'data-remove-level': '' }, 'Quitar nivel'));
    head.appendChild(box);
    criteria().forEach(function (row) { row.appendChild(newCell(box.querySelector('input').value, '0')); });
    renumber();
    box.querySelector('input').select();
  });

  board.addEventListener('click', function (event) {
    var removeCriterion = event.target.closest('[data-remove-criterion]');
    var removeLevel = event.target.closest('[data-remove-level]');
    if (removeCriterion && criteria().length > 1) {
      removeCriterion.closest('[data-criterion]').remove();
      renumber();
    } else if (removeLevel && levels().length > minLevels) {
      var position = levels().indexOf(removeLevel.closest('[data-level]'));
      removeLevel.closest('[data-level]').remove();
      criteria().forEach(function (row) { row.querySelectorAll('[data-cell]')[position].remove(); });
      renumber();
    }
  });

  board.addEventListener('input', function (event) {
    if (event.target.closest('#rub-head')) renumber();  // el nombre del nivel se repite en cada celda (celular)
    else if (event.target.classList.contains('rub-points')) total();
  });

  form.addEventListener('submit', renumber);
  renumber();
})();
