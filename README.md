# Academic Notes

Plataforma web para docentes: grupos, lista de alumnos, esquema de evaluación, actividades y entregas, quizzes con calificación automática, libreta de calificaciones y reportes (boleta PDF, concentrado Excel y alumnos en riesgo). Construida con **Django**.

> El plan de producto por fases, los planes y precios y la ruta hacia el cobro viven en [`New_Phases.md`](New_Phases.md).

---

## ✨ Qué incluye

| Área | App | Descripción |
|---|---|---|
| Organizaciones | `organizations` | Multi-tenant por fila: `Organization`, `Membership`, selector de organización activa, planes y límites (`plans.py`, `limits.py`), pantalla «Plan y facturación» |
| Cuentas | `accounts` | Login por correo o usuario, confirmación de correo, restablecer y cambiar contraseña, perfil editable y foto privada |
| Grupos y alumnos | `courses` | Ciclos escolares, grupos archivables y duplicables, lista de alumnos, importación Excel/CSV con vista previa, código de invitación |
| Calificaciones | `grades` | Esquema de evaluación (periodos y criterios), actividades con borrador/publicación, entregas con archivos privados, calificar con penalización por tardía, historial, libreta con edición en línea |
| Quizzes | `quizzes` | Banco de preguntas, constructor, resolver con plazo del servidor y autoguardado, calificación automática, importar preguntas, cierre de intentos vencidos |
| Reportes | `reports` | Boleta PDF, concentrado Excel con columnas elegibles, alumnos en riesgo |
| Mensajería | `messaging` | Conversaciones docente ↔ alumno y notificaciones |
| Alta y precios | `onboarding` | Portada, registro de docente y de alumno, términos y privacidad (**borrador sin revisión legal**), primeros pasos, página de Precios con lista de espera, Ayuda |

---

## 💳 Planes

Los topes y funciones de cada plan están en una sola tabla: `apps/organizations/plans.py` (se consultan con `apps/organizations/limits.py`). Hoy **no hay cobro en línea**: el plan de pago se asigna desde el admin y la página `/precios/` recoge una lista de espera.

| | Gratis | Docente |
|---|---|---|
| Grupos activos | 2 | sin tope |
| Alumnos en grupos activos | 60 | sin tope |
| Preguntas en el banco | 30 | sin tope |
| Quizzes con tiempo límite | no | sí |
| Excel con columnas a elección | no (columnas fijas) | sí |
| Boletas PDF | con marca de agua | sin marca de agua |
| Precio | $0 | $149/mes · $1,490/año (MXN) |

Los planes de institución y Docente Plus se asignan a mano y no tienen topes.

---

## 🧱 Stack

- **Django 5.2**. Desarrollo local con Python 3.14 (entorno conda `DjangoEnvironment`); el CI y el Dockerfile usan Python 3.13.
- **SQLite** en local sin Docker; **PostgreSQL 16** en Docker, CI y producción.
- **Celery + Redis** para correos y cierre de intentos de quiz. En local, `CELERY_TASK_ALWAYS_EAGER=True` corre las tareas en el mismo proceso, sin worker.
- Plantillas Django con CSS y JS propios (`static/css/gradelink.css`, `static/js/`).
- `openpyxl` (Excel), `reportlab` (PDF), `Pillow` (fotos).
- Pruebas con **pytest + pytest-django + factory_boy**; lint con **ruff**.

---

## 📁 Estructura

```
Academic-Notes/
├── core/             # Settings (base/local/production/test), urls, Celery, throttle, utilidades
├── apps/
│   ├── accounts/  courses/  grades/  messaging/
│   └── onboarding/  organizations/  quizzes/  reports/
├── templates/        # Plantillas HTML (auth, emails, onboarding, partials…)
├── static/           # CSS y JS propios
├── requirements/     # base.txt, local.txt, production.txt
├── conftest.py       # Fixtures compartidas de la suite
├── New_Phases.md     # Plan de producto
└── manage.py
```

Convenciones del código: la lógica va en `services/`, no en las vistas; todo modelo con organización hereda `TenantModel` y se consulta con `.for_organization(request.organization)`.

---

## 🚀 Puesta en marcha (local)

```bash
# 1. Activar el entorno (conda, como se usa en este proyecto)
conda activate DjangoEnvironment

# 2. Instalar dependencias
pip install -r requirements/local.txt

# 3. Variables de entorno
cp .env.example .env               # el valor por defecto usa SQLite y correos por consola

# 4. Migrar la base de datos
python manage.py migrate

# 5. Datos de ejemplo (docente, alumnos, grupos, quizzes, entregas…)
python manage.py crear_demo

# 6. Levantar el servidor
python manage.py runserver         # → http://127.0.0.1:8000/
```

`crear_demo` crea el docente `docente@demo.test` y los alumnos `alumno1@demo.test` a `alumno3@demo.test`, todos con la contraseña `Demo-Clave-2026`. Solo corre con `DEBUG=True` o con `--force`. Opciones: `--reset` (rehacer la escuela), `--delete` (borrarla).

Para crear un administrador: `python manage.py createsuperuser`.

### Con Docker

```bash
docker compose up --build          # web + PostgreSQL + Redis + worker de Celery
```

---

## ✅ Pruebas y calidad

```bash
pytest                             # toda la suite (settings: core.settings.test)
ruff check .                       # lint
python manage.py makemigrations --check --dry-run   # ¿faltan migraciones?
```

El CI (`.github/workflows/ci.yml`) corre estas tres comprobaciones con PostgreSQL y Redis en cada push a `main` y `develop`.

---

## 🗺️ Rutas principales

| URL | Descripción |
|---|---|
| `/` | Portada (o el panel, según el rol, si ya iniciaste sesión) |
| `/registro/` · `/registro/alumno/` | Registro de docente y de alumno |
| `/login/` | Inicio de sesión |
| `/precios/` | Planes y lista de espera del plan de pago |
| `/profesor/dashboard/` · `/alumno/dashboard/` | Panel por rol |
| `/grupo/<id>/` | Detalle del grupo |
| `/grupo/<id>/libreta/` | Libreta de calificaciones |
| `/grupo/<id>/concentrado/` · `/grupo/<id>/riesgo/` | Reportes del grupo |
| `/actividades/<id>/` | Actividad (entregas, calificar, historial) |
| `/banco/` | Banco de preguntas |
| `/mensajes/` | Mensajería |
| `/perfil/` · `/ajustes/` · `/ajustes/plan/` · `/ayuda/` | Perfil, ajustes, plan y facturación, ayuda |
| `/admin/` | Panel de administración de Django |

Las rutas antiguas `/materia/…` redirigen (301) a `/grupo/…`.

---

## ⚙️ Variables de entorno

Se leen de `.env` (plantilla en `.env.example`). Las principales:

| Variable | Para qué |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `core.settings.local` (desarrollo) o `core.settings.production` |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Configuración básica de Django |
| `DATABASE_URL` | Vacía = SQLite local; con Docker/producción, la URL de PostgreSQL |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_TASK_ALWAYS_EAGER` | Caché y Celery |
| `DJANGO_EMAIL_BACKEND`, `EMAIL_*`, `DEFAULT_FROM_EMAIL` | Correo (por defecto, a consola) |
| `SITE_NAME`, `SITE_URL`, `SUPPORT_EMAIL` | Nombre, dirección pública (obligatoria en producción) y soporte; salen en los correos |
| `SENTRY_DSN` | Errores en producción (opcional) |

---

## 🧭 Estado y hoja de ruta

- **Hecho:** organizaciones multi-tenant, ciclos y grupos, esquema de evaluación, actividades y entregas, quizzes, libreta, reportes, registro, planes y límites sin cobro, página de Precios.
- **Siguiente:** corregir lo que salga de las pruebas manuales; luego la pasarela de pago en modo de prueba, y el despliegue con respaldos probados.
- **Más adelante:** asistencia, rúbricas, proyectos por equipos, panel de dirección, API (`api/v1`) y app móvil. Detalle en [`New_Phases.md`](New_Phases.md).

---

## 🔒 Notas

- `db.sqlite3`, `.env`, `media/` y `private_media/` están en `.gitignore`: cada quien genera su base local con `migrate` y `crear_demo`.
- Las entregas de los alumnos y las fotos de perfil se guardan en `private_media/` (privado, fuera de `/media/`). En producción debe ser un volumen persistente o almacenamiento tipo S3.
- Los intentos de quiz abiertos pasado su plazo se cierran con Celery beat cada minuto (`celery -A core beat`, ya incluido en `docker compose`) o a mano con `python manage.py cerrar_intentos_vencidos`.
- Producción exige `SITE_URL`; el remitente (`no-reply@academicnotes.app`) y el correo de soporte son marcadores hasta tener un dominio real.
- Los textos de términos y privacidad son un borrador y necesitan revisión legal antes de lanzar.
