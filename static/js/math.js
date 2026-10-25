/* Fórmulas y ecuaciones: convierte \( ... \) (en línea) y \[ ... \] (en bloque) en matemáticas con KaTeX.
 *
 * No se usa $...$ a propósito: en los problemas de escuela se escribe «cuesta $15» y no debe volverse fórmula.
 * KaTeX lee el texto ya escapado por Django (no inserta HTML del usuario) y se le quitan las funciones que
 * podrían abusar (`trust: false`, tope de tamaño y de expansión de macros). Lo que escribe un alumno
 * (respuestas cortas o abiertas) va dentro de `.no-math` y nunca se interpreta.
 */
(function () {
  "use strict";

  var OPTIONS = {
    delimiters: [
      { left: "\\[", right: "\\]", display: true },
      { left: "\\(", right: "\\)", display: false },
    ],
    ignoredClasses: ["no-math"],
    throwOnError: false,
    trust: false,
    strict: "ignore",
    maxSize: 30,
    maxExpand: 200,
  };

  function render(root) {
    if (typeof window.renderMathInElement !== "function") {
      return;
    }
    window.renderMathInElement(root || document.body, OPTIONS);
  }

  window.AcademicMath = { render: render, options: OPTIONS };
  render(document.body);
})();
