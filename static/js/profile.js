// Perfil: «Editar perfil» lleva al formulario y la foto elegida se ve antes de guardar.
(function () {
  var MAX_BYTES = 5 * 1024 * 1024;
  var input = document.getElementById('id_avatar');
  var preview = document.getElementById('avatar-preview');
  var error = document.getElementById('avatar-error');
  var remove = document.querySelector('input[name="remove_avatar"]');
  var previewUrl = null;

  function showError(text) {
    if (error) { error.textContent = text; }
  }

  if (input && preview) {
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      showError('');
      if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
      if (!file) { return; }
      if (file.size > MAX_BYTES) {
        input.value = '';
        showError('La foto pesa más de 5 MB.');
        return;
      }
      if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
        input.value = '';
        showError('Sube una foto en formato JPG, PNG o WebP.');
        return;
      }
      previewUrl = URL.createObjectURL(file);
      var circle = preview.querySelector('.avatar');
      circle.textContent = '';
      var img = document.createElement('img');
      img.alt = '';
      img.src = previewUrl;
      circle.appendChild(img);
      if (remove) { remove.checked = false; }
    });
  }

  var edit = document.querySelector('[data-edit-profile]');
  if (edit) {
    edit.addEventListener('click', function (ev) {
      ev.preventDefault();
      var card = document.getElementById('editar-perfil');
      if (!card) { return; }
      card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      card.classList.add('is-editing');
      setTimeout(function () { card.classList.remove('is-editing'); }, 1600);
      var first = card.querySelector('input[name="first_name"]');
      if (first) { first.focus({ preventScroll: true }); }
    });
  }
})();
