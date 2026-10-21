// Pantallas de acceso: botón para mostrar u ocultar la contraseña.
(function () {
  'use strict';

  document.querySelectorAll('input[type="password"]').forEach(function (input) {
    var wrap = document.createElement('div');
    wrap.className = 'pw';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'pw-toggle';
    toggle.textContent = 'Mostrar';
    toggle.setAttribute('aria-pressed', 'false');
    toggle.setAttribute('aria-label', 'Mostrar la contraseña');
    wrap.appendChild(toggle);

    toggle.addEventListener('click', function () {
      var visible = input.type === 'password';
      input.type = visible ? 'text' : 'password';
      toggle.textContent = visible ? 'Ocultar' : 'Mostrar';
      toggle.setAttribute('aria-pressed', String(visible));
      toggle.setAttribute('aria-label', visible ? 'Ocultar la contraseña' : 'Mostrar la contraseña');
    });
  });
})();
