/* Resolver un quiz: guardado periódico de respuestas y temporizador.
 *
 * El tiempo lo manda y lo vigila el servidor: aquí solo se cuenta hacia atrás a partir de los segundos que
 * el servidor dice que quedan, y se vuelven a sincronizar en cada guardado.
 */
(function () {
  "use strict";

  var form = document.getElementById("quiz-form");
  if (!form) {
    return;
  }

  var autosaveUrl = form.dataset.autosaveUrl;
  var remaining = form.dataset.remaining === "" ? null : parseInt(form.dataset.remaining, 10);
  var status = document.getElementById("save-status");
  var timer = document.getElementById("timer");
  var syncedAt = performance.now();
  var pending = null;
  var saving = false;
  var dirty = false;
  var submitting = false;

  function csrfToken() {
    return form.querySelector("[name=csrfmiddlewaretoken]").value;
  }

  function collect() {
    var data = new FormData();
    data.append("csrfmiddlewaretoken", csrfToken());
    form.querySelectorAll("input[type=radio]:checked").forEach(function (input) {
      data.append(input.name, input.value);
    });
    // Las respuestas de texto se mandan siempre, también vacías: así borrar lo escrito se guarda.
    form.querySelectorAll("input[type=text], textarea").forEach(function (input) {
      data.append(input.name, input.value);
    });
    return data;
  }

  function setStatus(text) {
    if (status) {
      status.textContent = text;
    }
  }

  function save() {
    if (submitting) {
      return;
    }
    if (saving) {
      dirty = true;
      return;
    }
    saving = true;
    dirty = false;
    setStatus("Guardando…");
    fetch(autosaveUrl, { method: "POST", body: collect(), credentials: "same-origin" })
      .then(function (response) {
        return response.json().then(function (body) {
          return { status: response.status, body: body };
        });
      })
      .then(function (result) {
        if (result.status === 409 && result.body.expired) {
          submitting = true;
          window.location.href = result.body.url;
          return;
        }
        if (result.body.ok) {
          setStatus("Respuestas guardadas");
          if (result.body.remaining !== null && result.body.remaining !== undefined) {
            remaining = result.body.remaining;
            syncedAt = performance.now();
          }
        } else {
          setStatus(result.body.error || "No se pudo guardar");
        }
      })
      .catch(function () {
        setStatus("Sin conexión: se reintentará");
        dirty = true;
      })
      .then(function () {
        saving = false;
        if (dirty) {
          schedule();
        }
      });
  }

  function schedule() {
    clearTimeout(pending);
    pending = setTimeout(save, 700);
  }

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function format(seconds) {
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = seconds % 60;
    return (h ? h + ":" + pad(m) : m) + ":" + pad(s);
  }

  function tick() {
    if (remaining === null || !timer) {
      return;
    }
    var left = Math.max(0, remaining - Math.floor((performance.now() - syncedAt) / 1000));
    timer.textContent = format(left);
    timer.classList.toggle("timer-low", left <= 60);
    if (left <= 0 && !submitting) {
      // Se acabó el tiempo: se envía lo que haya y el servidor decide qué cuenta.
      submitting = true;
      form.submit();
    }
  }

  form.addEventListener("change", schedule);
  form.addEventListener("submit", function (event) {
    if (submitting) {
      return;
    }
    var total = form.querySelectorAll(".quiz-question").length;
    var answered = form.querySelectorAll("input[type=radio]:checked").length;
    var missing = total - answered;
    var noun = form.getAttribute("data-noun") || "quiz";
    var message = missing > 0
      ? "Te faltan " + missing + " pregunta(s) por responder. ¿Enviar el " + noun + " de todos modos?"
      : "¿Enviar el " + noun + "? Ya no podrás cambiar tus respuestas.";
    if (!window.confirm(message)) {
      event.preventDefault();
      return;
    }
    submitting = true;
  });

  setInterval(save, 30000);
  if (remaining !== null) {
    tick();
    setInterval(tick, 1000);
  }
})();
