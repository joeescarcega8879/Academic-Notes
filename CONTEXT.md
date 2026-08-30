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

## Próximas Fases

### ⬜ Fase 3 — App `subjects` (Materias e Inscripciones)

Modelos: `Subject`, `Enrollment`
Vistas: ProfessorDashboardView, StudentDashboardView, SubjectDetailView (reemplazan los placeholders `professor_dashboard` / `student_dashboard` en `apps/subjects/urls.py`)
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
