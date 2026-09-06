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
| `credenciales-prueba/` | Scripts `crear_usuarios.py` (20 usuarios demo) y `crear_datos_demo.py` (5 materias + 17 inscripciones). `.txt` con credenciales. **No versionado** |

**Bug encontrado en verificación:** `handle_no_permission` accedía a `user.role` con usuario anónimo (`AnonymousUser` no tiene `role`) → 500. Fix: si no está autenticado → `super().handle_no_permission()` (redirige a `/login/?next=...`).

**Verificación:** smoke test 14/14 con `django.test.Client`: dashboards 200, detalle 200, materia no inscrita 404, cruce de roles 302 al dashboard correcto, anónimos 302 a login, placeholders F4/F5 siguen 200. `manage.py check` sin errores.

**Pendiente Fase 4:** reemplazar el `StudentDashboardView` placeholder de `total_students`/stats con promedios reales cuando exista `grades`.

---

## Próximas Fases

### ⬜ Fase 4 — App `grades` (Evaluaciones y Calificaciones)

Modelos: `Evaluation`, `Grade`
Vistas: GradeListView, GradeCreateView, GradeUpdateView, GradeDeleteView
Templates: `calificaciones.html`

### ⬜ Fase 5 — App `messaging` (Mensajería)

Modelos: `Conversation`, `Message`
Vistas: ConversationListView, ConversationDetailView, MessageCreateView
Templates: `mensajes.html`

### ⬜ Fase 6 — Integración y Pulido

Dashboard stats reales, notificaciones, exportar periodo, responsive, dark mode
