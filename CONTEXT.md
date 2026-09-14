# Academic Notes — Contexto del Proyecto

## Fases Completadas

### ✅ Fase 1 — Infraestructura Base

**Archivos creados/modificados:**

| Archivo | Acción |
|---|---|
| `core/settings.py` | Agregados: `TEMPLATES_DIR`, `STATIC_DIR`, `MEDIA_DIR`, `STATICFILES_DIRS`, `MEDIA_URL`, `MEDIA_ROOT`, `LANGUAGE_CODE=es-mx`, `TIME_ZONE`, `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL`. DB cambiada a SQLite. |
| `core/urls.py` | Reescribir con includes de las 4 apps + media en DEBUG |
| `apps/__init__.py` | Creado (vacío) |
| `apps/accounts/urls.py` | Creado (vacío) |
| `apps/subjects/urls.py` | Creado (vacío) |
| `apps/grades/urls.py` | Creado (vacío) |
| `apps/messaging/urls.py` | Creado (vacío) |
| `static/css/gradelink.css` | Copiado desde front-end |
| `static/js/icons.js` | Copiado desde front-end |
| `static/js/app.js` | Copiado desde front-end |
| `templates/` | Directorio creado |
| `media/` | Directorio creado |

**Verificación:** `python manage.py migrate` ejecutado, `python manage.py runserver` funcional.

---

### ✅ Fase 2 — App `accounts` (Autenticación y Perfiles)

**Archivos creados/modificados:**

| Archivo | Acción |
|---|---|
| `apps/accounts/models.py` | `User` (AbstractUser con `email` único, `role`, `dni`, `phone`, preferencias), `StudentProfile`, `ProfessorProfile`, `UserManager` custom |
| `apps/accounts/backends.py` | `EmailOrUsernameBackend` (login con email o username) |
| `apps/accounts/forms.py` | `LoginForm`, `ProfileForm`, `StudentProfileForm`, `ProfessorProfileForm` |
| `apps/accounts/views.py` | `LoginView` (con role picker), `LogoutView`, `ProfileView` (con perfil extra según rol) |
| `apps/accounts/urls.py` | Rutas: `/login/`, `/logout/`, `/perfil/` |
| `apps/accounts/admin.py` | `CustomUserAdmin` con campos de rol y preferencias |
| `core/settings.py` | `AUTH_USER_MODEL = 'accounts.User'`, `AUTHENTICATION_BACKENDS` |
| `templates/base.html` | Layout global con sidebar dinámico (profesor/alumno), topbar, modals, tweaks, scripts |
| `templates/partials/sidebar.html` | Sidebar con datos reales del usuario, `is-active` automático por `request.resolver_match` |
| `templates/partials/modals.html` | Modales compartidos: crear/editar evaluación y confirmar eliminación |
| `templates/login.html` | Convertido a Django template con `{% csrf_token %}`, `{{ form }}`, role picker funcional |
| `templates/perfil.html` | Extiende `base.html`, formulario con datos reales, preferencias, perfil extra según rol |

**Verificación:** Login con email o username, redirección por rol, perfil con guardado de datos.

---

### ✅ Fase 2.1 — Correcciones

**Archivos creados/modificados:**

| Archivo | Acción |
|---|---|
| `apps/accounts/models.py` | `User.dni` ahora `null=True` (antes `unique=True, blank=True` → colisión de `''` entre usuarios sin DNI) |
| `apps/accounts/migrations/0002_alter_user_dni.py` | Migración generada y aplicada |
| `apps/accounts/views.py` | `LoginView._dashboard_url` usa `reverse('professor_dashboard' / 'student_dashboard')` en vez de rutas hardcodeadas, con fallback a `profile` |
| `apps/subjects/urls.py` | Placeholders `professor_dashboard` (`/profesor/dashboard/`), `student_dashboard` (`/alumno/dashboard/`) con `TemplateView` |
| `apps/grades/urls.py` | `app_name = 'grades'` + placeholder `grades:list` (`/calificaciones/`) |
| `apps/messaging/urls.py` | `app_name = 'messaging'` + placeholder `messaging:list` (`/mensajes/`) |
| `templates/placeholder.html` | Página "Próximamente" que extiende `base.html` |

**Motivo:** `partials/sidebar.html` ya referenciaba esos nombres de URL, por lo que cualquier página que extendía `base.html` (incl. `/perfil/`) fallaba con `NoReverseMatch`.

**Verificación:** `manage.py check` sin errores; `/perfil/`, dashboards, `/calificaciones/` y `/mensajes/` responden 200 para profesor y alumno.

**Pendiente para Fases 3–5:** reemplazar cada `TemplateView` placeholder por su vista real; los nombres de URL ya quedan fijados.

---

### ✅ Fase 3 — App `subjects` (Materias e Inscripciones)

**Archivos creados/modificados:**

| Archivo | Acción |
|---|---|
| `apps/subjects/models.py` | Modelos `Subject` (name, code único, description, schedule, color, professor FK) y `Enrollment` (student, subject, enrolled_at, `unique_together`) |
| `apps/subjects/migrations/0001_initial.py` | Migración inicial creada y aplicada |
| `apps/subjects/admin.py` | `SubjectAdmin` y `EnrollmentAdmin` registrados |
| `apps/subjects/views.py` | `ProfessorDashboardView`, `StudentDashboardView` (con role check) y `SubjectDetailView` (acceso por rol; 404 si no inscrito) |
| `apps/subjects/urls.py` | Rutas reales: `professor_dashboard`, `student_dashboard`, `subject_detail` (`/materia/<int:pk>/`) — reemplazan los placeholders |
| `templates/dashboard-profesor.html` | Dashboard profesor: stats (materias, alumnos únicos, departamento) + grid de materias con contador de inscritos |
| `templates/dashboard-alumno.html` | Dashboard alumno: stats + grid de sus materias inscritas |
| `templates/materia.html` | Detalle según rol: profesor → tabla de alumnos; alumno → info de su inscripción |
| `apps/accounts/models.py` | `__str__` en `StudentProfile` y `ProfessorProfile` (admin legible) |
| `static/js/app.js` | Fix: eliminado el intercept del submit de login del front-end estático (navegaba a `dashboard-*.html` → 404). El login ahora hace POST normal a Django |
| `.gitignore` | Creado: ignora `__pycache__`, `db.sqlite3`, `credenciales-prueba/`, `media/`, venvs |
| `credenciales-prueba/` | Scripts `crear_usuarios.py` (10 profesores + 10 estudiantes demo) y `crear_datos_demo.py` (8 materias + 40 inscripciones). `.txt` con credenciales. **No versionado** |

**Bug encontrado en verificación:** `handle_no_permission` accedía a `user.role` con usuario anónimo (`AnonymousUser` no tiene `role`) → 500. Fix: si no está autenticado → `super().handle_no_permission()` (redirige a `/login/?next=...`).

**Verificación:** smoke test 14/14 con `django.test.Client`: dashboards 200, detalle 200, materia no inscrita 404, cruce de roles 302 al dashboard correcto, anónimos 302 a login, placeholders F4/F5 siguen 200. `manage.py check` sin errores.

**Pendiente Fase 4:** reemplazar el `StudentDashboardView` placeholder de `total_students`/stats con promedios reales cuando exista `grades`. → **Resuelto en Fase 4.**

---

### ✅ Fase 4 — App `grades` (Evaluaciones y Calificaciones)

**Archivos creados/modificados:**

| Archivo | Acción |
|---|---|
| `apps/grades/models.py` | Modelos `Evaluation` (subject FK, title, description, type, max_score, weight, date) y `Grade` (evaluation FK, student FK, score, feedback, graded_at, `unique_together`) |
| `apps/grades/migrations/0001_initial.py` | Migración inicial creada y aplicada |
| `apps/grades/admin.py` | `EvaluationAdmin` y `GradeAdmin` registrados |
| `apps/grades/forms.py` | `GradeForm` con querysets filtrados por rol (solo evaluaciones y alumnos de las materias del profesor) + validación en `clean()`: alumno inscrito en la materia y nota ≤ `max_score` |
| `apps/grades/views.py` | `GradeAccessMixin` / `ProfessorRequiredMixin`; `GradeListView` (filtra por rol), `GradeCreateView`, `GradeUpdateView`, `GradeDeleteView` (solo profesor) |
| `apps/grades/urls.py` | Rutas reales: `grades:list`, `grades:create`, `grades:update`, `grades:delete` — reemplazan el placeholder |
| `templates/calificaciones.html` | Listado según rol: profesor con acciones y botón "Nueva calificación"; alumno en solo lectura |
| `templates/calificacion_form.html` | Formulario crear/editar calificación |
| `templates/calificacion_confirm_delete.html` | Confirmación de borrado |
| `apps/subjects/views.py` | `StudentDashboardView` calcula el **promedio ponderado real** (`Sum(score*weight)/Sum(weight)`) |
| `templates/dashboard-alumno.html` | Muestra `{{ average }}` en vez del placeholder `—`; encabezado con `{% block topbar %}` |
| `credenciales-prueba/crear_usuarios.py` | Script idempotente: 10 profesores + 10 estudiantes demo (`@academicnotes.test`, contraseñas `Profesor123!` / `Alumno123!`) y `credenciales.txt`. **No versionado** |

**Bug encontrado en verificación:** un formateador (Prettier) partió dos etiquetas Django en varias líneas dentro de `calificaciones.html` (un `{% endif %}` y un `{% else %}` cortados por un salto de línea). Django **no reconoce** etiquetas `{% %}` que cruzan un salto de línea → `TemplateSyntaxError` (500 en `/calificaciones/`). Fix: unir cada etiqueta en una sola línea. **Recomendación:** no ejecutar formateadores HTML sobre `templates/` (añadir `.prettierignore`).

**Corrección adicional:** `calificaciones.html`, `calificacion_form.html` y `dashboard-alumno.html` usaban `{% block top %}` y/o `<header class="header">`, que no existen ni en `base.html` (el bloque es `topbar`) ni en el CSS (la clase es `.topbar`). El encabezado no se renderizaba, perdiendo el botón "Nueva calificación". Fix: `top` → `topbar` y `header` → `topbar`.

**Verificación:** los 12 templates parsean; `/calificaciones/` y `/calificaciones/nueva/` → 200 con CSRF válido (profesor); `/calificaciones/` → 200 (alumno); POST crear con CSRF → 200; `manage.py check` sin errores; 0 etiquetas partidas en `templates/`.

---

### ✅ Fase 4.1 — Correcciones y pulido (rol alumno)

**Motivo:** al probar la Fase 4 se detectó que el alumno no podía ver sus calificaciones: el sidebar no enlazaba a la lista completa y el detalle de materia no mostraba ninguna nota.

**Archivos creados/modificados:**

| Archivo | Acción |
|---|---|
| `apps/grades/forms.py` | `GradeForm`: asigna `class="select"` / `class="input"` a cada widget (los campos no tomaban los estilos del front-end). Añade `label_from_instance`: alumno → nombre completo (o email), evaluación → solo el título |
| `templates/calificacion_form.html` | Wrapper `form-field` → `field` (la clase real del CSS). Mensajes de error con estilos inline, porque `alert alert-error` y `text-error` no existen en el CSS |
| `templates/partials/sidebar.html` | Alumno: enlace **Mis Materias** (dashboard) + **Mis Calificaciones** (`grades:list`, antes inexistente). Fix de `is-active`: comparaba `url_name == 'grades:list'` (que es `'list'`); ahora usa `view_name`. **Perfil** deja de estar siempre activo |
| `apps/subjects/views.py` | `StudentDashboardView`: promedio ponderado **por materia** en cada enrollment. `SubjectDetailView`: para alumno, `evaluation_rows` (evaluación + su calificación) y `subject_average` |
| `templates/materia.html` | Vista alumno: tabla de evaluaciones y calificaciones + promedio de la materia |
| `templates/dashboard-alumno.html` | Cada card muestra el **promedio de la materia** (antes `—` fijo) |
| `apps/grades/models.py` | Etiquetas de `Evaluation.Type` traducidas: `Examen`, `Tarea`, `Proyecto` (estaban en inglés). `__str__` con separador `·` |
| `apps/grades/migrations/0002_alter_evaluation_type.py` | Migración por cambio de `choices` (generada y aplicada) |
| `credenciales-prueba/crear_datos_demo.py` | Script idempotente: 8 materias (asignadas a 8 profesores demo) + 40 inscripciones (cada alumno en 4 materias). **No versionado** |

**Verificación:** los 12 templates parsean; sidebar alumno con enlace a `/calificaciones/` y `is-active` correcto; `materia.html` muestra evaluaciones, nota y promedio de la materia; dashboard muestra el promedio por materia; lista completa en `/calificaciones/`; regresión profesor 200; `manage.py check` sin errores. Pruebas con datos temporales (creados y borrados).

---

## Próximas Fases

### ⬜ Fase 5 — App `messaging` (Mensajería)

Modelos: `Conversation`, `Message`
Vistas: ConversationListView, ConversationDetailView, MessageCreateView
Templates: `mensajes.html`

### ⬜ Fase 6 — Integración y Pulido

Dashboard stats reales, notificaciones, exportar periodo, responsive, dark mode
