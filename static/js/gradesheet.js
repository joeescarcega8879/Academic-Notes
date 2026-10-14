/* Libreta: edición de calificaciones en línea.
 *
 * Cada celda se guarda sola al salir de ella (o con Enter). Las peticiones salen de una en una, en orden, y
 * lo que se ve después de guardar es siempre lo que respondió el servidor (nota, final del alumno, promedios).
 */
(function () {
  "use strict";

  var table = document.getElementById("gradesheet");
  if (!table) {
    return;
  }

  var url = table.dataset.cellUrl;
  var csrf = document.querySelector("#gs-csrf [name=csrfmiddlewaretoken]").value;
  var status = document.getElementById("gs-status");
  var filter = document.getElementById("gs-filter");
  var chain = Promise.resolve();
  var inFlight = 0;

  function setStatus(text, isError) {
    if (status) {
      status.textContent = text;
      status.style.color = isError ? "var(--bad)" : "";
    }
  }

  function setText(selector, text) {
    var node = table.querySelector(selector);
    if (node) {
      node.textContent = text;
    }
  }

  function setNote(cell, text, isError) {
    var note = cell.querySelector(".gs-note");
    note.textContent = text;
    cell.classList.toggle("is-error", !!isError);
  }

  function apply(input, sent, body) {
    var cell = input.closest("td");
    var row = input.closest("tr");
    var activity = input.dataset.activity;

    input.dataset.original = body.cell.raw;
    input.dataset.note = body.cell.note;
    // Si el docente ya siguió escribiendo en la misma celda, no se le pisa lo que tiene.
    if (input.value.trim() === sent) {
      input.value = body.cell.raw;
      setNote(cell, body.cell.note, false);
    }
    cell.classList.toggle("is-auto", body.cell.auto);

    var final = row.querySelector(".gs-final");
    final.dataset.passed = body.final.passed === null ? "" : String(body.final.passed);
    final.querySelector(".gs-final-value").textContent = body.final.text || "—";
    row.classList.toggle("gs-risk", body.final.passed === false);

    setText('[data-avg="' + activity + '"]', body.column.average || "—");
    setText('[data-count="' + activity + '"]', body.column.graded);
    setText("[data-group-average]", body.group.average || "—");
    setText("[data-group-passed]", body.group.passed);
    setText("[data-group-students]", body.group.students);

    cell.classList.add("is-saved");
    window.setTimeout(function () {
      cell.classList.remove("is-saved");
    }, 900);
  }

  function send(input, sent) {
    var cell = input.closest("td");
    var data = new FormData();
    data.append("csrfmiddlewaretoken", csrf);
    data.append("activity", input.dataset.activity);
    data.append("student", input.closest("tr").dataset.student);
    data.append("score", sent);

    inFlight += 1;
    setStatus("Guardando…", false);
    return fetch(url, { method: "POST", body: data, credentials: "same-origin" })
      .then(
        function (response) {
          return response.json().then(
            function (body) {
              return { ok: response.ok && body.ok === true, body: body };
            },
            function () {
              return { ok: false, body: { error: "No se pudo guardar (error " + response.status + ")." } };
            }
          );
        },
        function () {
          return { ok: false, body: { error: "Sin conexión: no se guardó." } };
        }
      )
      .then(function (result) {
        inFlight -= 1;
        cell.classList.remove("is-saving");
        if (result.ok) {
          apply(input, sent, result.body);
          if (inFlight === 0) {
            setStatus("Cambios guardados", false);
          }
        } else {
          setNote(cell, result.body.error || "No se guardó.", true);
          setStatus("Hay celdas sin guardar", true);
        }
      });
  }

  function save(input) {
    var sent = input.value.trim();
    if (sent === input.dataset.original) {
      return;
    }
    input.closest("td").classList.add("is-saving");
    chain = chain.then(function () {
      return send(input, sent);
    });
  }

  function revert(input) {
    var cell = input.closest("td");
    input.value = input.dataset.original;
    setNote(cell, input.dataset.note || "", false);
  }

  function move(input, step) {
    var column = input.closest("td").cellIndex;
    var row = input.closest("tr");
    do {
      row = step > 0 ? row.nextElementSibling : row.previousElementSibling;
    } while (row && row.hidden);
    var target = row && row.cells[column] && row.cells[column].querySelector(".gs-input");
    if (target) {
      target.focus();
    } else {
      input.blur();
    }
  }

  table.addEventListener("change", function (event) {
    if (event.target.classList.contains("gs-input")) {
      save(event.target);
    }
  });

  table.addEventListener("focusin", function (event) {
    if (event.target.classList.contains("gs-input")) {
      event.target.select();
    }
  });

  table.addEventListener("keydown", function (event) {
    var input = event.target;
    if (!input.classList.contains("gs-input")) {
      return;
    }
    if (event.key === "Enter" || event.key === "ArrowDown") {
      event.preventDefault();
      move(input, 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(input, -1);
    } else if (event.key === "Escape") {
      revert(input);
      input.select();
    }
  });

  // Las notas de cada celda se recuerdan para poder deshacer con Escape.
  table.querySelectorAll(".gs-input").forEach(function (input) {
    input.dataset.note = input.closest("td").querySelector(".gs-note").textContent;
  });

  function plain(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  if (filter) {
    var rows = Array.prototype.slice.call(table.tBodies[0].rows);
    var names = rows.map(function (row) {
      return plain(row.dataset.name);
    });
    filter.addEventListener("input", function () {
      var query = plain(filter.value.trim());
      rows.forEach(function (row, index) {
        row.hidden = query !== "" && names[index].indexOf(query) === -1;
      });
    });
  }

  window.addEventListener("beforeunload", function (event) {
    if (inFlight > 0) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
})();
