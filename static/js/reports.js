/* Concentrado en Excel: reordenar las columnas con las flechas.
 *
 * El orden en que se envían las casillas es el del documento, así que basta con mover los renglones.
 */
(function () {
  "use strict";

  var list = document.getElementById("rpt-columns");
  if (!list) {
    return;
  }

  list.addEventListener("click", function (event) {
    var button = event.target.closest("[data-move]");
    if (!button) {
      return;
    }
    var item = button.closest("li");
    var step = parseInt(button.dataset.move, 10);
    var target = step < 0 ? item.previousElementSibling : item.nextElementSibling;
    if (!target) {
      return;
    }
    if (step < 0) {
      list.insertBefore(item, target);
    } else {
      list.insertBefore(target, item);
    }
    button.focus();
  });
})();
