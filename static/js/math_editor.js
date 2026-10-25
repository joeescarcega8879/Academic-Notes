/* Editor de fórmulas del formulario de preguntas: una paleta de símbolos y una vista previa en vivo.
 *
 * El docente no necesita saber LaTeX: los botones escriben la fórmula en el campo donde estaba escribiendo. Quien ya
 * la conoce puede teclear \( ... \) (en línea) o \[ ... \] (en bloque) a mano. La vista previa usa el mismo KaTeX
 * que ven los alumnos (`AcademicMath`, de math.js).
 *
 * Campos con fórmulas: la pregunta, la explicación y las opciones, los elementos a ordenar y la columna izquierda de
 * las de relacionar. No las respuestas aceptadas de una respuesta corta (se comparan como texto) ni la columna
 * derecha de relacionar (va en un menú, que no admite formato).
 */
(function (root) {
  "use strict";

  // Marca de dónde queda el cursor dentro de una plantilla (no se usa en matemáticas, a diferencia de «|»).
  var MARK = "\u2038";

  // [etiqueta del botón, LaTeX con «‸» donde queda el cursor, ayuda]
  var GROUPS = [
    ["Álgebra", [
      ["a/b", "\\frac{‸}{}", "Fracción"], ["xⁿ", "^{‸}", "Exponente"], ["xₙ", "_{‸}", "Subíndice"], ["√", "\\sqrt{‸}", "Raíz cuadrada"],
      ["ⁿ√", "\\sqrt[‸]{}", "Raíz n-ésima"], ["| |", "\\left| ‸ \\right|", "Valor absoluto"], ["( )", "\\left( ‸ \\right)", "Paréntesis grandes"],
      ["Sistema", "\\begin{cases} ‸ \\\\  \\end{cases}", "Sistema de ecuaciones"], ["Σ", "\\sum_{i=1}^{‸}", "Sumatoria"]]],
    ["Operadores", [
      ["±", "\\pm ", "Más o menos"], ["×", "\\times ", "Por"], ["÷", "\\div ", "Entre"], ["·", "\\cdot ", "Punto"], ["≠", "\\neq ", "Distinto"],
      ["≤", "\\le ", "Menor o igual"], ["≥", "\\ge ", "Mayor o igual"], ["≈", "\\approx ", "Aproximado"], ["∞", "\\infty ", "Infinito"]]],
    ["Griegas", [
      ["π", "\\pi ", "pi"], ["θ", "\\theta ", "theta"], ["α", "\\alpha ", "alfa"], ["β", "\\beta ", "beta"], ["Δ", "\\Delta ", "Delta"],
      ["λ", "\\lambda ", "lambda"]]],
    ["Geometría", [
      ["°", "^{\\circ}", "Grados"], ["∠", "\\angle ", "Ángulo"], ["⊥", "\\perp ", "Perpendicular"], ["∥", "\\parallel ", "Paralelas"],
      ["△", "\\triangle ", "Triángulo"], ["→", "\\vec{‸}", "Vector"]]],
    ["Cálculo", [
      ["lím", "\\lim_{x \\to ‸}", "Límite"], ["∫", "\\int_{‸}^{} ", "Integral"], ["d/dx", "\\frac{d}{dx}", "Derivada"], ["sen", "\\sin ", "Seno"],
      ["cos", "\\cos ", "Coseno"], ["log", "\\log_{‸}", "Logaritmo"]]],
  ];

  // Tipos de pregunta cuyas opciones (el campo «-text» de cada fila) admiten fórmulas.
  var KINDS_WITH_MATH_OPTIONS = ["multiple_choice", "ordering", "matching"];

  /** ¿La posición ``pos`` ya está dentro de una fórmula abierta con \( o \[ ? */
  function insideMath(text, pos) {
    var before = text.slice(0, pos);
    return before.lastIndexOf("\\(") > before.lastIndexOf("\\)") || before.lastIndexOf("\\[") > before.lastIndexOf("\\]");
  }

  /**
   * Inserta ``template`` en ``text`` entre ``start`` y ``end``. Con texto seleccionado lo envuelve; dentro de una fórmula
   * ya abierta no repite los delimitadores; fuera de una, usa \( \) (o \[ \] si es un bloque como un sistema).
   * Devuelve ``{ value, caret }``: el texto nuevo y dónde queda el cursor.
   */
  function insertSnippet(text, start, end, template) {
    var selection = text.slice(start, end);
    var inside = insideMath(text, start);
    var marker = template.indexOf(MARK);
    var fragment = template.replace(MARK, selection);
    var caret;
    if (selection) {
      // Lo seleccionado ya entró en la plantilla: el cursor pasa al siguiente hueco ({}) o al final.
      var gap = fragment.indexOf("{}");
      caret = gap !== -1 ? gap + 1 : fragment.length;
    } else {
      caret = marker !== -1 ? marker : fragment.length;
    }
    var block = !inside && template.indexOf("\\begin") === 0;
    var open = inside ? "" : (block ? "\\[" : "\\(");
    var close = inside ? "" : (block ? "\\]" : "\\)");
    return {
      value: text.slice(0, start) + open + fragment + close + text.slice(end),
      caret: start + open.length + caret,
    };
  }

  var api = { GROUPS: GROUPS, insideMath: insideMath, insertSnippet: insertSnippet };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.MathEditor = api;

  // ── Parte del navegador ──────────────────────────────────────────────

  function init(form) {
    var holder = form.querySelector("[data-math-palette]");
    if (!holder || !root.AcademicMath) {
      return;
    }
    var kind = form.getAttribute("data-kind") || "";
    var current = form.querySelector("#id_text");
    var target = null;

    function isMathField(el) {
      if (!el || (el.tagName !== "TEXTAREA" && el.tagName !== "INPUT") || el.type === "hidden" || el.type === "checkbox") {
        return false;
      }
      if (el.id === "id_text" || el.id === "id_explanation") {
        return true;
      }
      return KINDS_WITH_MATH_OPTIONS.indexOf(kind) !== -1 && Boolean(el.closest("#choices")) && /-text$/.test(el.name);
    }

    function fieldName(el) {
      if (el.id === "id_text") {
        return "Pregunta";
      }
      if (el.id === "id_explanation") {
        return "Explicación";
      }
      var rows = Array.prototype.slice.call(form.querySelectorAll("#choices .choice-row"));
      var index = rows.indexOf(el.closest(".choice-row")) + 1;
      return (kind === "multiple_choice" ? "Opción " : "Elemento ") + index;
    }

    function buildPalette() {
      holder.setAttribute("role", "toolbar");
      holder.setAttribute("aria-label", "Símbolos y fórmulas");
      holder.classList.add("mx-paleta");
      // Un grupo a la vez, en pestañas: así la paleta ocupa una sola fila y puede quedarse a la vista al bajar por el formulario.
      var tabs = document.createElement("div");
      tabs.className = "mx-tabs";
      tabs.setAttribute("role", "tablist");
      var panel = document.createElement("div");
      panel.className = "mx-fila";
      panel.setAttribute("role", "tabpanel");

      // El botón no le quita el foco al campo: así el cursor sigue donde estaba.
      function keepFocus(button) {
        button.addEventListener("mousedown", function (event) { event.preventDefault(); });
      }

      function select(index) {
        Array.prototype.forEach.call(tabs.children, function (tab, i) {
          tab.setAttribute("aria-selected", i === index ? "true" : "false");
        });
        panel.textContent = "";
        GROUPS[index][1].forEach(function (item) {
          var button = document.createElement("button");
          button.type = "button";
          button.className = "mx-btn";
          button.textContent = item[0];
          button.title = item[2];
          button.setAttribute("aria-label", item[2]);
          keepFocus(button);
          button.addEventListener("click", function () { insert(item[1]); });
          panel.appendChild(button);
        });
      }

      GROUPS.forEach(function (group, index) {
        var tab = document.createElement("button");
        tab.type = "button";
        tab.className = "mx-tab";
        tab.setAttribute("role", "tab");
        tab.textContent = group[0];
        keepFocus(tab);
        tab.addEventListener("click", function () { select(index); });
        tabs.appendChild(tab);
      });
      holder.appendChild(tabs);
      holder.appendChild(panel);
      select(0);
      var where = document.createElement("p");
      where.className = "mx-destino";
      where.innerHTML = "Los botones escriben en: <strong data-math-target>Pregunta</strong>. " +
        "Dentro de una fórmula se insertan sin repetirla; con texto seleccionado, lo envuelven.";
      holder.appendChild(where);
    }

    function setTarget(el) {
      current = el;
      var label = holder.querySelector("[data-math-target]");
      if (label) {
        label.textContent = fieldName(el);
      }
    }

    function previewFor(el) {
      if (el._mxPreview && el._mxPreview.isConnected) {
        return el._mxPreview;
      }
      var box = document.createElement("div");
      box.className = "mx-vista";
      box.setAttribute("aria-live", "polite");
      var anchor = el.closest(".choice-row") || el;
      anchor.insertAdjacentElement("afterend", box);
      el._mxPreview = box;
      return box;
    }

    function refresh(el) {
      var value = el.value;
      var hasMath = value.indexOf("\\(") !== -1 || value.indexOf("\\[") !== -1;
      if (!hasMath) {
        if (el._mxPreview) {
          el._mxPreview.remove();
          el._mxPreview = null;
        }
        return;
      }
      var box = previewFor(el);
      box.textContent = value;
      root.AcademicMath.render(box);
    }

    function insert(template) {
      var el = current;
      if (!el) {
        return;
      }
      var start = typeof el.selectionStart === "number" ? el.selectionStart : el.value.length;
      var end = typeof el.selectionEnd === "number" ? el.selectionEnd : start;
      var result = insertSnippet(el.value, start, end, template);
      el.value = result.value;
      el.focus();
      el.setSelectionRange(result.caret, result.caret);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }

    buildPalette();
    form.addEventListener("focusin", function (event) {
      if (isMathField(event.target)) {
        setTarget(event.target);
      }
    });
    form.addEventListener("input", function (event) {
      if (isMathField(event.target)) {
        if (event.target !== current) {
          setTarget(event.target);  // escribir en un campo lo vuelve el destino aunque no haya avisado el foco
        }
        refresh(event.target);
      }
    });
    if (current) {
      setTarget(current);
    }
    form.querySelectorAll("textarea, input[type=text]").forEach(function (el) {
      if (isMathField(el)) {
        refresh(el);
      }
    });
  }

  if (typeof document !== "undefined") {
    var start = function () {
      var form = document.querySelector("form[data-math-editor]");
      if (form) {
        init(form);
      }
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
