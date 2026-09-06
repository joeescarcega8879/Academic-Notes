# Academic Notes · GradeLink

Sistema web académico construido con **Django** para la gestión de materias,
calificaciones y comunicación entre **profesores** y **alumnos**
(prototipo · Universidad del Plata Sur).

> 📄 **Contexto del proyecto:** el historial técnico completo — fases, archivos,
> decisiones y pendientes — vive en **[CONTEXT.md](CONTEXT.md)**. Este README es la
> guía rápida; el CONTEXT.md es el registro de trabajo.

---

## ✨ Funcionalidades

| Área | Estado | Descripción |
|---|---|---|
| Autenticación | ✅ Fase 2 | Login con **email o username**, selector de rol, logout, perfiles con datos académicos y preferencias |
| Materias e inscripciones | ✅ Fase 3 | Dashboards por rol, materias con horario/color, inscripción de alumnos, detalle con tabla de inscritos |
| Calificaciones | ⬜ Fase 4 | Evaluaciones, calificaciones y promedios (en desarrollo) |
| Mensajería | ⬜ Fase 5 | Conversaciones profesor ↔ alumno (en desarrollo) |
| Integración y pulido | ⬜ Fase 6 | Stats reales, notificaciones, exportar, responsive, dark mode |

---

## 🧱 Stack

- **Django 5.2** · Python 3.14 (entorno conda `DjangoEnvironment`)
- **SQLite** (base de datos local, no versionada)
- Templates Django + **CSS/JS propios** (front *GradeLink* copiado al proyecto) con iconos Feather inline
- Admin de Django para gestión (materias, inscripciones, usuarios)

---

## 📁 Estructura del proyecto

```
Academic-Notes/
├── core/                  # Settings y urls del proyecto
├── apps/
│   ├── accounts/          # User custom, perfiles, login, backends
│   ├── subjects/          # Subject, Enrollment, dashboards
│   ├── grades/            # (Fase 4) Evaluaciones y calificaciones
│   └── messaging/         # (Fase 5) Mensajería
├── templates/             # HTML: base, login, perfil, dashboards, materia…
├── static/                # css/gradelink.css, js/app.js, js/icons.js
├── media/                 # Subidas de usuario (avatares)
├── credenciales-prueba/   # ⚠️ LOCAL (no versionado): usuarios y datos demo
├── CONTEXT.md             # Contexto técnico detallado del proyecto
└── manage.py
```

---

## 🚀 Puesta en marcha

```bash
# 1. Activar el entorno (conda, como se usa en este proyecto)
conda activate DjangoEnvironment

# 2. Instalar dependencias (si hace falta)
pip install "django>=5.2"

# 3. Migrar la base de datos y crear superusuario
python manage.py migrate
python manage.py createsuperuser   # pide email, rol y contraseña

# 4. Levantar el servidor
python manage.py runserver         # → http://127.0.0.1:8000/
```

---

## 👥 Datos de demostración (opcional)

El proyecto incluye scripts locales (en `credenciales-prueba/`, **no versionados**)
para poblar la base de datos al instante:

```bash
python credenciales-prueba/crear_usuarios.py      # 10 profesores + 10 alumnos con perfiles
python credenciales-prueba/crear_datos_demo.py    # 5 materias + 17 inscripciones
```

**Credenciales** (ver `credenciales-prueba/credenciales.txt`):

| Rol | Email | Contraseña |
|---|---|---|
| Profesor | `jose.ramirez@gradelink.edu` | `Test1234!` |
| Alumno | `diego.morales@gradelink.edu` | `Test1234!` |

---

## 🗺️ Rutas principales

| URL | Descripción |
|---|---|
| `/login/` | Inicio de sesión (selector de rol) |
| `/profesor/dashboard/` | Dashboard del profesor (sus materias + alumnos) |
| `/alumno/dashboard/` | Dashboard del alumno (materias inscritas) |
| `/materia/<pk>/` | Detalle de materia (tabla de alumnos / info de inscripción) |
| `/perfil/` | Perfil y preferencias del usuario |
| `/calificaciones/` | *(Fase 4)* — placeholder actual |
| `/mensajes/` | *(Fase 5)* — placeholder actual |
| `/admin/` | Panel de administración |

---

## 🔒 Notas

- `db.sqlite3` y `credenciales-prueba/` están en `.gitignore`: cada quien genera
  su base local con `migrate` + scripts demo.
- Las credenciales de prueba son únicamente para desarrollo local.
- Para el registro técnico por fases (qué se creó, por qué y cómo se verificó),
  consulta **[CONTEXT.md](CONTEXT.md)**.
