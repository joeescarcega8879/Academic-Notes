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

## Próximas Fases

### ⬜ Fase 3 — App `subjects` (Materias e Inscripciones)

Modelos: `Subject`, `Enrollment`
Vistas: ProfessorDashboardView, StudentDashboardView, SubjectDetailView
Templates: `dashboard-profesor.html`, `dashboard-alumno.html`, `materia.html`

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
