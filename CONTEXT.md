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

### ✅ Fase 5 — App `messaging` (Mensajería)

**Archivos creados/modificados:**

| Archivo | Acción |
|---|---|
| `apps/messaging/models.py` | Modelos `Conversation` (subject FK, student FK, `unique_together`) y `Message` (conversation FK, sender FK, body, `read_at`), con índices sobre `(conversation, created_at)` y `(conversation, read_at)` |
| `apps/messaging/signals.py` | `post_save`/`post_delete` sobre `subjects.Enrollment`: crea/elimina la `Conversation` al inscribirse/desinscribirse |
| `apps/messaging/apps.py` | `ready()` importa `signals` |
| `apps/messaging/context_processors.py` | `unread_messages(request)` → `unread_count` para el badge del sidebar |
| `core/settings.py` | Registrado `apps.messaging.context_processors.unread_messages` en `TEMPLATES` |
| `apps/messaging/forms.py` | `MessageForm` (solo `body`, clase `input`, `clean_body` rechaza vacío) |
| `apps/messaging/views.py` | `MessagingAccessMixin`, `ConversationQuerysetMixin` (`base_queryset`, `conversations_for`, `group_by_day`, `with_other`), `ConversationListView`, `ConversationDetailView` (marca leídos al abrir), `MessageCreateView` |
| `apps/messaging/urls.py` | Rutas reales `messaging:list`, `messaging:detail`, `messaging:send` — reemplazan el `TemplateView` placeholder |
| `apps/messaging/admin.py` | `ConversationAdmin` con `MessageInline`, `MessageAdmin` |
| `apps/messaging/migrations/0001_initial.py` | Migración inicial (generada y aplicada) |
| `apps/messaging/migrations/0002_backfill_conversations.py` | Migración de datos: crea la conversación de cada `Enrollment` preexistente |
| `templates/mensajes.html` | Split-pane `.msg-layout`: lista de conversaciones + chat con burbujas in/out agrupadas por día y formulario de envío |
| `templates/partials/sidebar.html` | `is-active` de Mensajes por `resolver_match.app_name == 'messaging'` |

**Bugs encontrados en verificación (corregidos):**

1. **Faltaba la migración de datos.** El signal solo cubre inscripciones nuevas: la base tenía 40 `Enrollment` y **0 `Conversation`**, así que el buzón salía vacío para todos y no había forma de crear hilos desde la UI. Se añadió `0002_backfill_conversations` → 40 conversaciones.
2. **`{{ c.counterpart|default:c.student }}` no funcionaba.** `Conversation.counterpart(user)` requiere un argumento; el resolver de templates la llama sin argumentos, lanza `TypeError`, se atrapa en silencio y devuelve `string_if_invalid` (`''`) → el filtro `default` caía siempre a `c.student`. El **alumno veía su propio nombre/email** como título de la conversación. Fix: `with_other()` en el mixin resuelve `conversation.other` y el template usa `c.other`.
3. **`context_processors.py` con clave inconsistente:** las salidas tempranas devolvían `unread_messages_count` y la rama buena `unread_count`. Unificado a `unread_count`.
4. **`is-active` del sidebar** comparaba solo `messaging:list`, por lo que no se iluminaba en `/mensajes/<pk>/`.
5. **`MessageInline.fields`** omitía `body` (no se veía el texto del mensaje en el admin).
6. Nits: comentario obsoleto en `urls.py`, `from .import views`, docstrings y comentarios en inglés fuera del estilo del repo.

**Verificación:** `manage.py check` sin errores; `makemigrations --check --dry-run` → `No changes detected`; migraciones `0001` y `0002` aplicadas; base real con 8 materias · 40 inscripciones · **40 conversaciones** · 0 inscripciones sin conversación; **15/15 pruebas** con `django.test.Client` (lista 200 profesor/alumno, detalle participante 200, **detalle ajeno 404**, anónimo 302 a `/login/?next=`, POST crea mensaje con `sender` correcto, body vacío no crea, `unread_count` en contexto, badge del sidebar, marcar leído al abrir, contraparte correcta para ambos roles, `is-active` en detalle); los **13 templates** compilan y **0 etiquetas `{% %}` partidas**. Prueba manual end-to-end con las cuentas demo (`carlos.ramirez@academicnotes.test` / `ana.garcia@academicnotes.test`, ambos en *Estructuras de Datos*).

**Pruebas:** `apps/messaging/tests.py` contiene 15 pruebas permanentes (acceso por rol, envío, no leídos, contraparte, sidebar y signal de inscripción).

---

### ✅ Fase 6 — Integración y Pulido

**Archivos creados/modificados:**

| Archivo | Acción |
|---|---|
| `apps/grades/views.py` | `GradeExportView`: CSV con BOM para Excel, filtros `materia` / `desde` / `hasta`, columnas según rol (el profesor incluye Alumno/Email) |
| `apps/grades/urls.py` | Ruta `grades:export` (`/calificaciones/exportar/`) |
| `apps/subjects/views.py` | `ProfessorDashboardView` con stats reales: promedio del grupo, tasa de aprobación, evaluaciones, calificadas, y promedio/tasa por materia |
| `templates/dashboard-profesor.html` | 6 stats reales + promedio y tasa de aprobación en cada tarjeta de materia |
| `apps/accounts/context_processors.py` | **Nuevo.** `notifications(request)` → `notifications` + `notifications_count` |
| `core/settings.py` | Registrado el context processor; `LANGUAGE_CODE='es-mx'`; `TIME_ZONE='America/Mexico_City'` |
| `templates/partials/notifications.html` | **Nuevo.** Campana con badge y panel desplegable |
| `templates/{dashboard-profesor,dashboard-alumno,materia,calificaciones,mensajes}.html` | Campana real (antes `.pip` fijo) vía `{% include %}` |
| `templates/calificaciones.html` | Barra de exportación: select de materia + rango de fechas + botón CSV |
| `templates/mensajes.html` | Clase `has-active` en `.msg-layout` y botón `.chat-back` para móvil |
| `static/css/gradelink.css` | Cajón lateral móvil, chat alternado lista/detalle, tablas con scroll horizontal, panel de notificaciones, `.chat-back`, `.export-bar` |
| `static/js/app.js` | Tema persistido en `localStorage`, aplicado en `<html>`; `setupNotifications()` y `setupNavToggle()`; **eliminadas las funciones muertas del prototipo** (`escapeHtml` se conservó porque `setupEvalTable` la usa) |
| `templates/base.html` | Script de pre-carga del tema (sin parpadeo) + botón de menú y scrim móvil |
| `.prettierignore` | **Nuevo.** Excluye `templates/` (evita el bug de Fase 4 con etiquetas `{% %}` partidas) |
| `apps/messaging/tests.py` | 15 pruebas permanentes (antes vacío) |

**Decisiones y alcance:**

- **Tasa de aprobación** = 60% del puntaje máximo de la evaluación (`PASS_RATIO = 0.6` en `apps/subjects/views.py`).
- **Notificaciones**: mensajes sin leer para ambos roles; calificaciones de los últimos 7 días solo para alumnos y solo si `notify_grades` está activo.
- **`notify_weekly` / `notify_sms` quedan sin efecto**: son canales externos (email/SMS) que requieren SMTP o un gateway; no se implementaron. Siguen guardándose como preferencia del perfil.
- **Código muerto eliminado**: `setupChat()`, `setupConversations()`, `setupClarify()` y `applyRefFromUrl()` apuntaban al prototipo estático (`#chat-form`, `data-who`, `mensajes.html?ref=`). `setupConversations()` enganchaba un listener en cada `.conv-item`; no rompía la navegación (no hacía `preventDefault` y sus `dataset` eran `undefined`), pero era una trampa latente.

**Incidente durante la implementación:** al añadir CSS se usó una lectura truncada a ~4500 caracteres y se sobrescribió `static/css/gradelink.css` (47713 → 7151 bytes). Se detectó de inmediato, se restauró desde git y se reaplicaron los cambios con un script que lee y escribe el archivo completo. **Lección: nunca reescribir un archivo a partir de una lectura truncada.**

**Verificación:** `manage.py check` sin errores; `makemigrations --check --dry-run` → `No changes detected`; **28/28 pruebas** (15 de messaging + 13 de Fase 6: export CSV con BOM y filtros, stats del profesor con valores exactos, notificaciones por rol y preferencia, y layout móvil de mensajería); los **14 templates** compilan con 0 etiquetas partidas; `node --check static/js/app.js` → sintaxis válida; locale confirmado `es-mx` / `America/Mexico_City`; smoke test con datos reales: 10/10 rutas 200 para profesor y alumno, barra de exportación y panel de notificaciones presentes, CSV con cabecera correcta.

---

## Estado del Roadmap

Las 6 fases planificadas están completas. Queda trabajo opcional:

- **Mixin de acceso compartido**: `GradeAccessMixin` / `ProfessorRequiredMixin` y `MessagingAccessMixin` están duplicados en 3 apps; candidato a `apps/accounts/mixins.py`.
- **Adjuntos en mensajería**: el CSS tiene el ícono `paperclip` pero no hay modelo de archivos.
- **Crear conversaciones manualmente** y búsqueda server-side en el buzón.
- **Canales de notificación reales** (`notify_weekly`, `notify_sms`).
- **Persistir las pruebas de Fase 6** (hoy son temporales, viven fuera del repo).
