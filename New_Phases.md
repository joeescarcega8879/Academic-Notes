# GradeLink — Plan de producto e implementación

> Plataforma de calificaciones, actividades y comunicación para docentes e instituciones educativas de habla hispana. Este documento es la referencia de producto, arquitectura y hoja de ruta. No contiene código; describe **qué** se construye, **en qué orden** y **por qué**.

---

## Índice

1. [Visión y propuesta de valor](#1-visión-y-propuesta-de-valor)
2. [Ediciones y precios](#2-ediciones-y-precios)
3. [Módulos del producto](#3-módulos-del-producto)
4. [Módulo de actividades](#4-módulo-de-actividades)
5. [Arquitectura](#5-arquitectura)
6. [Hoja de ruta web por fases](#6-hoja-de-ruta-web-por-fases)
7. [Reglas transversales de escalabilidad](#7-reglas-transversales-de-escalabilidad)
8. [Plan de aplicación móvil (Flutter)](#8-plan-de-aplicación-móvil-flutter)
9. [Principios de diseño para docentes](#9-principios-de-diseño-para-docentes)
10. [Aspectos legales y de negocio](#10-aspectos-legales-y-de-negocio)
11. [Métricas](#11-métricas)
12. [Riesgos](#12-riesgos)

---

## 1. Visión y propuesta de valor

**Frase de valor:** "Tu libreta de calificaciones, tus actividades y tu comunicación con alumnos, en un solo lugar y en 5 minutos de configuración."

**Nicho objetivo:** docentes de secundaria, preparatoria y universidad en México y Latinoamérica que hoy llevan calificaciones en Excel y necesitan ponderaciones, listas, boletas y actividades calificadas en un solo lugar, en español y sin curva de aprendizaje.

**Diferencia frente a la competencia:** Google Classroom es gratis pero no calcula promedios ponderados por criterio ni genera boletas; Moodle es potente pero requiere administración técnica. GradeLink se posiciona como la herramienta simple que resuelve el flujo real del docente: lista → esquema de evaluación → actividades → calificar → boleta.

**Estado de partida:** base Django con `accounts` (User personalizado, roles docente/alumno), `grades` y `messaging`. El plan agrega apps y ajusta las existentes; no hay reescrituras.

---

## 2. Ediciones y precios

| | Docente (individual) | Institución |
|---|---|---|
| Quién compra | Un profesor con su tarjeta | Director / coordinador académico |
| Alcance | Sus grupos y alumnos | Toda la escuela, varios docentes |
| Extras | — | Panel de dirección, portal de padres, reportes globales, SSO, soporte |
| Ciclo de venta | Autoservicio, minutos | Demo + piloto + contrato, 1–3 meses |

### Edición Docente

| Plan | Precio | Límites |
|---|---|---|
| Gratis | $0 | 2 grupos, 60 alumnos, sin exámenes cronometrados, sin exportar PDF |
| Docente | $129–179 MXN/mes · $1,290–1,790 MXN/año | Grupos ilimitados, todas las actividades, banco de preguntas, reportes PDF/Excel |
| Docente Plus | $249–299 MXN/mes | + IA para quizzes, WhatsApp, almacenamiento ampliado |

El plan anual ofrece 2 meses gratis; es donde vive el margen.

### Edición Institución (cobro anual)

| Plan | Por alumno/año | Alternativa por docente/año | Incluye |
|---|---|---|---|
| Básico | $60–90 MXN | $2,000–2,500 MXN | Hasta 300 alumnos, panel director, reportes globales |
| Estándar | $90–140 MXN | $2,500–3,500 MXN | Hasta 1,500 alumnos, portal de padres, asistencia, soporte prioritario |
| Enterprise | Cotización (desde $30,000 MXN/año) | — | Ilimitado, SSO, capacitación, exportaciones personalizadas, SLA |

Estrategia de entrada: piloto gratuito de un periodo para las primeras 5 escuelas a cambio de testimonios.

---

## 3. Módulos del producto

| # | Módulo | Descripción | Edición |
|---|---|---|---|
| 1 | Grupos y alumnos | Crear grupo dentro de un ciclo escolar, importar lista desde Excel/CSV (con matrícula), código de invitación, archivar y duplicar grupo para nuevo ciclo | Ambas |
| 2 | Esquema de evaluación | Criterios ponderados por periodo, escalas configurables, redondeo, mínimo aprobatorio | Ambas |
| 3 | Actividades | Tareas, quizzes, exámenes, proyectos, participación (ver sección 4) | Ambas |
| 4 | Entregas y calificación | Bandeja de entregas, rúbricas, comentarios, política de tardías | Ambas |
| 5 | Asistencia | Pase de lista rápido, porcentaje como criterio opcional | Ambas |
| 6 | Reportes | Boleta PDF, concentrado Excel, alumnos en riesgo, avance del periodo | Ambas |
| 7 | Comunicación | Avisos al grupo, mensajes directos, correo; WhatsApp en Fase 3 | Ambas |
| 8 | Portal del alumno | Ver actividades, entregar, ver calificaciones y retroalimentación | Ambas |
| 9 | Institución | Ciclos escolares, planes de estudio, asignación docente-grupo-materia, panel del director, portal de padres | Institución |

### Alumnos, matrícula y ciclos escolares

**El alumno de la lista no es la cuenta.** Al importar desde Excel los alumnos aún no tienen usuario, y muchos nunca lo tendrán (docentes que usan GradeLink solo como libreta). Por eso existe `Student`, separado de `User`:

- `Student`: organización, matrícula, nombre(s), apellidos, correo opcional, `user` (FK nullable que se enlaza cuando el alumno usa el código de invitación).
- `Enrollment` apunta a `Student`, no a `User`.
- **Matrícula:** `CharField` opcional (nunca entero: hay ceros a la izquierda y letras). Única por organización cuando no está vacía. Vive en `Student` porque pertenece a la institución, no a la persona ni al curso.
- El importador lee la columna de matrícula **como texto** (Excel la convierte a número o notación científica) y la usa como **llave de re-importación** (upsert): subir la lista actualizada no duplica alumnos.
- Toda exportación (concentrado Excel, boleta) incluye la matrícula. El docente elige y ordena las columnas del concentrado, porque el formato que exige cada sistema de control escolar (SEP estatal, universidad) varía y no se intenta adivinar.
- CURP: solo si las entrevistas lo piden, y siempre opcional (dato personal de menores; ver sección 10).

**Ciclos escolares: crear nuevo y archivar, nunca renombrar.** Renombrar un grupo para reutilizarlo mezcla las calificaciones, boletas y `GradeHistory` del ciclo anterior con el nuevo.

- `AcademicYear` ligero desde la Fase 1: organización, nombre ("2026–2027", "Ago–Dic 2026"), fechas, `is_current`. `Course` lleva FK a él. El Sprint 8 lo extiende; no hay migración posterior.
- `Course.status` (`active` / `archived`) y `archived_at`. Un curso archivado es de **solo lectura**, sale de la vista principal y sigue siendo consultable y exportable.
- Acción **"Duplicar para nuevo ciclo"** (`services/courses.py: clone_course()`): copia esquema de evaluación, rúbricas y actividades (como borradores sin fechas). No copia alumnos, inscripciones, entregas ni calificaciones. El banco de preguntas ya es por organización y se reutiliza solo.
- Los `Student` persisten en la organización; en el nuevo ciclo solo se crean `Enrollment` nuevos. La promoción masiva de grupos (2°A → 3°A) es del Sprint 8.
- **Límites de plan:** los cursos archivados no cuentan contra el límite de grupos; desarchivar pasa por `check_limit`.
- Ciclo ≠ periodo: el ciclo es el año o semestre; los periodos (parciales, bimestres) viven dentro de él y los cubre `EvaluationScheme`.

---

## 4. Módulo de actividades

### Modelo conceptual

`Activity` es la base: curso, criterio de evaluación, tipo, título, instrucciones, puntos, fecha de apertura, fecha de entrega, permite tardías, penalización %, publicada. Cada tipo agrega comportamiento:

| Tipo | Comportamiento | Fase |
|---|---|---|
| Tarea (`homework`) | Entrega de archivo/texto/enlace; calificación manual o con rúbrica | 1 |
| Quiz (`quiz`) | Preguntas cortas, calificación automática, retroalimentación inmediata | 1 |
| Participación (`class_participation`) | Sin entrega; calificación rápida en lista | 1 |
| Examen (`exam`) | Ventana de apertura/cierre, tiempo límite, intentos, orden aleatorio | 2 |
| Proyecto (`project`) | Entrega por equipos, hitos, rúbrica obligatoria | 2 |
| Foro (`forum`) | Discusión calificada | 3 |

### Constructor de preguntas

- Tipos: opción múltiple, verdadero/falso (Fase 1); respuesta corta con coincidencia normalizada, respuesta abierta manual, relacionar columnas, ordenar (Fase 2).
- Cada pregunta tiene puntos, explicación y etiqueta de tema.
- **Banco de preguntas** por organización y materia, reutilizable; genera retención.

### Rúbricas

Plantillas `Rubric` → `RubricCriterion` → `RubricLevel` (criterios × niveles con puntos), reutilizables entre actividades y grupos.

### Automatizaciones

- Recalculo del promedio ponderado al calificar.
- Alertas de alumnos por debajo del mínimo.
- Recordatorios a alumnos 24 h antes de la entrega.
- Fase 3: generación de quizzes con IA (con revisión obligatoria del docente), detección de plagio básica.

---

## 5. Arquitectura

### Backend

- **Django + Django REST Framework.** Apps: `organizations`, `accounts`, `courses`, `grades`, `activities`, `submissions`, `reports`, `messaging`, `billing`, `api`.
- **Multi-tenant por fila:** modelo `Organization`; todo modelo relevante lleva FK a ella. El docente individual es una organización de un solo miembro. No se usan esquemas separados por tenant al inicio.
- **`Membership`** (usuario, organización, rol: `owner`, `teacher`, `student`, `admin`, `coordinator`, `parent`). Un usuario puede tener roles distintos en organizaciones distintas.
- **Frontend web:** plantillas Django + HTMX/Alpine.js para el MVP. Migrar a un framework SPA solo si el constructor de exámenes lo exige.
- **Tareas asíncronas:** Celery + Redis (PDFs, correos, recordatorios, recálculos masivos, importaciones).
- **Archivos:** S3 o compatible (MinIO en local) desde el primer sprint que maneje entregas.
- **Pagos:** Mercado Pago o Conekta para México (tarjeta, OXXO, SPEI); Stripe para el resto de LATAM. CFDI vía PAC (Facturama u otro).
- **API:** `api/v1/` con DRF, JWT (`djangorestframework-simplejwt`), esquema OpenAPI con `drf-spectacular`. Es la base de la app móvil (sección 8).

### Infraestructura

- Docker Compose local (`web`, `db`, `redis`, `worker`).
- Despliegue inicial en Railway o Render; migración a AWS (ECS/App Runner, RDS, S3, CloudFront) cuando la carga o el costo lo justifiquen.
- Sentry, logs estructurados, respaldos diarios automáticos de PostgreSQL con restauración probada.

### Seguridad

- 2FA opcional, permisos por rol y por organización revisados en cada vista y endpoint.
- Auditoría de cambios en calificaciones (`GradeHistory`: quién, qué, cuándo).
- Prueba automatizada de aislamiento: un usuario de la organización A nunca ve datos de la B.

### Diagrama de dependencias entre apps

```
organizations ← accounts ← courses ← grades
                                   ← activities ← submissions ← reports
billing → organizations (solo)
messaging → courses, organizations
api → todas (capa de exposición, sin lógica de negocio)
```

---

## 6. Hoja de ruta web por fases

### Fase 0 — Cimientos (2 semanas)

**Objetivo:** dejar el proyecto listo para crecer sin deuda estructural.

Repositorio y entorno:
- Docker Compose con `web`, `db`, `redis`, `worker`.
- Settings divididos: `base`, `local`, `production`; secretos en `.env`.
- Ramas `main` / `develop` / `feature/*`. CI (GitHub Actions): ruff, pytest, verificación de migraciones.
- `pytest-django` + `factory_boy`. Cada modelo nuevo llega con factory y prueba.

Refactor de la base actual:
- App `organizations` con `Organization` (nombre, tipo `individual`/`institution`, plan, activa) y `Membership`.
- El rol fijo en `User` se sustituye por `Membership`.
- FK a `Organization` en todos los modelos de `grades` y `messaging`. Migración de datos: cada usuario existente obtiene una organización individual.
- Manager `for_organization(org)` en cada modelo; middleware que expone `request.organization`.

**Criterio de listo:** funciones actuales intactas, todas las consultas filtran por organización, suite de pruebas en CI.

### Fase 1 — MVP Docente vendible (10–12 semanas, 5 sprints)

| Sprint | Entregable | Modelos clave |
|---|---|---|
| 1 | Ciclo escolar, grupos, importación de alumnos desde Excel/CSV con vista previa y mapeo de columnas (matrícula como texto y llave de re-importación), código de invitación que enlaza `Student` con `User`, lista editable, archivar grupo y duplicarlo para nuevo ciclo | `AcademicYear`, `Course`, `Student`, `Enrollment` |
| 2 | Esquema de evaluación ponderado por periodo, plantilla por defecto, servicio de cálculo de promedios con pruebas de casos límite | `EvaluationScheme`, `EvaluationCriterion` |
| 3 | Actividades (tarea, quiz, participación), entregas, calificación con comentario, auditoría, portal del alumno, archivos en S3 | `Activity`, `Submission`, `Grade`, `GradeHistory` |
| 4 | Quiz con calificación automática, banco de preguntas, intentos, tiempo límite, guardado periódico | `Question`, `Choice`, `QuizConfig`, `QuizAttempt`, `Answer` |
| 5 | Libreta (alumnos × actividades, edición en línea), boleta PDF y concentrado Excel con matrícula y columnas configurables, alumnos en riesgo, planes y suscripción con webhooks, límites por plan, landing, onboarding | `Plan`, `Subscription` |

**Criterio de listo:** un docente se registra, importa su lista, configura ponderación, crea tarea y quiz, califica, descarga boletas y paga sin intervención manual. Correos transaccionales vía Celery. Desplegado con respaldos probados antes del primer cobro.

**Meta comercial:** 50 docentes activos, 10 pagando.

### Fase 2 — Exámenes completos e Institución (10–12 semanas, 5 sprints)

| Sprint | Entregable | Modelos clave |
|---|---|---|
| 6 | Examen con ventana y tiempo estricto, nuevos tipos de pregunta, rúbricas reutilizables, proyectos por equipos | `Rubric`, `RubricCriterion`, `RubricLevel`, `Team`, `TeamMember` |
| 7 | Asistencia optimizada para móvil, asistencia como criterio, avisos con confirmación de lectura, recordatorios automáticos | `AttendanceSession`, `AttendanceRecord` |
| 8 | Estructura institucional: extensión de `AcademicYear` (ya existe desde Sprint 1), periodos, materias, grupos, promoción de grupos entre ciclos, asignación docente-grupo-materia que genera cursos; roles `admin`/`coordinator`; invitación masiva | `Term`, `Subject`, `Group`, `TeachingAssignment` |
| 9 | Panel de dirección (avance de captura, promedios por grupo/materia, riesgo global, exportación oficial), portal de padres solo lectura, auditoría visible | — |
| 10 | Planes institucionales con cobro anual y CFDI manual, piloto con 2–3 escuelas con retroalimentación semanal | — |

**Meta comercial:** 2–3 escuelas piloto convertidas a contrato.

### Fase 3 — Escala (continuo, con ingresos)

- Notificaciones WhatsApp (API de Meta o proveedor).
- IA para generar quizzes desde tema o PDF, con revisión obligatoria.
- PWA instalable; app nativa Flutter (sección 8).
- Integraciones: importación desde Google Classroom, Google Drive, SSO con Google Workspace for Education.
- Migración a AWS.
- Programa de referidos docente–docente y CFDI automático.

---

## 7. Reglas transversales de escalabilidad

1. **Una app por dominio**, sin dependencias circulares (ver diagrama en sección 5).
2. **Lógica de negocio en servicios** (`services/grading.py`, `services/enrollment.py`, `services/limits.py`). Las vistas y los endpoints orquestan; los servicios deciden. Esto permite que web y API compartan la misma lógica.
3. **Todo lo lento va a Celery.**
4. **Toda consulta filtra por organización**, verificado por prueba automatizada.
5. **Límites de plan centralizados** en `check_limit(org, feature)`; nunca condicionales por plan regados en vistas. Los cursos archivados no cuentan contra el límite; desarchivar sí lo verifica.
6. **Feature flags** por organización (`django-waffle` o tabla propia).
7. **Migraciones reversibles**; los campos se deprecan antes de borrarse.
8. **Cada sprint termina desplegado en staging.**

---

## 8. Plan de aplicación móvil (Flutter)

### Cuándo empezar

La app móvil se construye **después de la Fase 1 web** y en paralelo con la Fase 2. Razones:

- La web valida qué funciones usan realmente los docentes; la app móvil debe llevar solo lo que se usa desde el teléfono.
- La app depende de una API estable; construirla antes obliga a mantener dos frentes que cambian a la vez.
- Los servicios de negocio (sección 7, regla 2) se escriben una sola vez y se exponen por API sin duplicar lógica.

### Principio: una sola app, navegación por rol

Una aplicación en las tiendas. Al iniciar sesión, la app muestra la experiencia según el rol de `Membership` en la organización activa (docente, alumno, padre). Evita mantener tres apps separadas.

### Qué va al móvil y qué no

| Va al móvil | Se queda en web |
|---|---|
| Pase de lista | Configuración del esquema de evaluación |
| Calificación rápida (participación, notas numéricas) | Constructor de exámenes y banco de preguntas |
| Revisar y calificar entregas con comentario | Importación de alumnos desde Excel |
| Avisos y mensajes, notificaciones push | Reportes institucionales y exportaciones |
| Alumno: ver actividades, entregar, responder quiz, ver calificaciones | Panel de dirección |
| Padre: calificaciones, asistencia, avisos | Facturación y planes |

### Fase M0 — API pública (4 semanas, durante Sprint 6–7 web)

- Endpoints `api/v1/` con DRF para: autenticación, organizaciones y membresías, cursos, alumnos, actividades, entregas, calificaciones, asistencia, avisos.
- JWT con refresh tokens; revocación por dispositivo.
- Versionado por URL (`/api/v1/`); nunca romper contratos sin nueva versión.
- OpenAPI con `drf-spectacular`; a partir del esquema se genera el cliente Dart (`openapi-generator`), lo que elimina modelos escritos a mano.
- Paginación por cursor en listas grandes, filtros por curso y periodo, campos `updated_at` en todo recurso (base del sincronizado offline).
- Endpoint de **registro de dispositivo** para push (token FCM/APNs asociado a usuario).
- Pruebas de contrato: cada endpoint con prueba de permisos por rol y aislamiento por organización.

### Fase M1 — App Docente (6–8 semanas)

- Inicio de sesión, selección de organización, lista de cursos.
- Pase de lista con un toque por alumno; funciona sin conexión y se sincroniza después.
- Libreta simplificada: tabla alumnos × actividades con edición de calificación numérica.
- Bandeja de entregas: ver archivo/texto, calificar, comentar.
- Avisos al grupo y mensajes.
- Notificaciones push: nueva entrega, mensaje recibido, recordatorio de captura.
- Publicación interna (TestFlight / Play Console pruebas internas) con 5–10 docentes reales.

### Fase M2 — Alumno (4–6 semanas)

- Actividades pendientes y calendario.
- Entrega de tarea (archivo desde cámara/galería, texto, enlace).
- Responder quiz y examen: el temporizador es **autoritativo en el servidor** (la app solo lo muestra); guardado periódico de respuestas; bloqueo al expirar.
- Calificaciones y retroalimentación por criterio y periodo.
- Push: nueva actividad, calificación publicada, recordatorio 24 h antes.

### Fase M3 — Padres y consolidación (3–4 semanas)

- Rol padre: calificaciones, asistencia, avisos de sus hijos (uno o varios).
- Cambio de organización dentro de la app.
- Publicación pública en App Store y Play Store.

### Fase M4 — Offline completo y pulido (continuo)

- Caché de lectura para todo (cursos, alumnos, actividades, calificaciones).
- Cola de escritura para asistencia y calificaciones rápidas; resolución de conflictos por `updated_at` del servidor, con registro en `GradeHistory`.
- Modo de bajo consumo de datos (miniaturas, carga diferida de archivos).
- Widgets de pantalla de inicio (próxima entrega, pendientes de calificar) si el uso lo justifica.

### Arquitectura Flutter recomendada

| Capa | Herramienta | Motivo |
|---|---|---|
| Organización del código | Feature-first (`features/attendance`, `features/grades`, …) con capas `data` / `domain` / `presentation` | Escala con el equipo y con las funciones |
| Estado | Riverpod | Testeable, sin boilerplate excesivo; Bloc es alternativa válida si se prefiere más estructura |
| Navegación | `go_router` | Deep links (abrir una entrega desde un push), rutas por rol |
| HTTP | `dio` + interceptores (token, refresh, reintentos) | Cliente generado desde OpenAPI encima |
| Modelos | `freezed` + `json_serializable` | Inmutabilidad y serialización sin errores manuales |
| Persistencia local | `drift` (SQLite) para caché y cola offline; `flutter_secure_storage` para tokens | Consultas tipadas, migraciones locales |
| Push | `firebase_messaging` (FCM en Android e iOS) | Un solo proveedor para ambas plataformas |
| Archivos | `image_picker`, `file_picker`, subida directa a S3 con URL prefirmada del backend | El servidor no recibe archivos grandes |
| Errores y métricas | `sentry_flutter`, eventos de uso propios | Mismo Sentry que el backend |
| Pruebas | Unitarias por servicio, widget tests en pantallas críticas, integración para inicio de sesión y pase de lista | — |

### Diseño móvil

- Reutilizar la misma paleta y terminología que la web ("grupo", "actividad", "criterio").
- Pantallas pensadas para una mano: pase de lista y calificación rápida con controles grandes.
- Sin funciones de configuración pesada; si algo requiere muchos campos, se redirige a la web.
- Modo oscuro desde el inicio (es barato con el sistema de temas de Flutter).

### Publicación y operación

- Cuentas de desarrollador: Apple Developer (anual) y Google Play (pago único). Tramitarlas al inicio de M1: la revisión de Apple puede tardar.
- CI/CD: GitHub Actions o Codemagic con Fastlane para builds firmados, TestFlight y pruebas internas de Play.
- Versionado semántico compartido con la API: la app declara la versión mínima de API que soporta; el backend responde con "actualiza la app" cuando queda obsoleta.
- Política de privacidad y formulario de seguridad de datos en ambas tiendas (obligatorio; ver sección 10).

### Dependencias con el plan web

| Necesita la app móvil | Debe existir en web |
|---|---|
| M0 API | Fase 1 completa (servicios de negocio estables) |
| M1 Docente | Sprint 7 (asistencia) terminado |
| M2 Alumno | Sprint 6 (examen con tiempo servidor) terminado |
| M3 Padres | Sprint 9 (rol padre) terminado |

---

## 9. Principios de diseño para docentes

- **Cero jerga técnica:** "grupo", "actividad", "criterio", "periodo".
- **Regla de los 3 clics:** crear grupo, crear actividad y calificar caben en tres pasos.
- **Plantillas por defecto:** esquema precargado editable, nunca pantalla vacía.
- **Importar, no capturar:** listas desde Excel, preguntas desde archivo, calificaciones desde CSV. La matrícula es la llave para re-importar sin duplicar.
- **Nuevo ciclo en un clic:** duplicar el grupo conserva esquema y actividades; el ciclo anterior queda archivado y consultable.
- **La libreta es la pantalla principal:** tabla alumnos × actividades con promedio, editable en línea.
- **Onboarding guiado** de 5 pasos con datos de ejemplo borrables.
- **Móvil funcional** para pase de lista y calificación rápida.

---

## 10. Aspectos legales y de negocio

- **Datos de menores:** aviso de privacidad conforme a la LFPDPPP, consentimiento de la institución, contrato de encargado de tratamiento con cada escuela. Se guarda el mínimo de datos del alumno: matrícula y nombre; CURP solo si es indispensable y siempre opcional.
- **Términos de servicio y SLA** diferenciados por edición.
- **CFDI** obligatorio para vender a instituciones.
- **Exportación y retención:** el docente puede llevarse todo en Excel al cancelar.
- **Persona moral / RFC con actividad empresarial** para contratos con escuelas.
- **Tiendas de apps:** política de privacidad pública, declaración de datos recopilados, cumplimiento de reglas sobre usuarios menores.

---

## 11. Métricas

| Métrica | Definición | Señal |
|---|---|---|
| Activación | Docente crea grupo y primera actividad en su primera sesión | < 40 % → problema de onboarding |
| Retención semanal | Docentes que regresan cada semana durante el periodo escolar | Base de todo lo demás |
| Conversión | Gratis → pago | Valida precio y límites del plan gratis |
| Churn mensual | Suscripciones canceladas / activas | > 5 % → investigar |
| Alumnos activos por docente | Alumnos que entregan o consultan al menos una vez por semana | Mide adopción real |
| Tiempo para calificar | Minutos desde abrir la bandeja hasta cerrar una actividad | Guía del diseño de la app móvil |
| NPS | Encuesta trimestral | — |

---

## 12. Riesgos

| Riesgo | Mitigación |
|---|---|
| Ciclo escolar: instituciones deciden mayo–julio y diciembre–enero | Tener piloto listo antes de esas ventanas |
| Soporte y capacitación consumen tiempo | Cobrarlos aparte o incluirlos solo en Enterprise |
| El módulo de exámenes se traga meses | MVP solo con opción múltiple y verdadero/falso |
| Un solo desarrollador | 15–20 h/semana sostenidas; no cambiar de stack a medio camino; móvil solo después de Fase 1 |
| Mantener web y móvil sincronizadas | Toda lógica en servicios; API versionada; app declara versión mínima de API |
| No se conoce el formato que exige el sistema de control escolar de cada docente (SEP estatal, universidad) | Exportación con matrícula y columnas configurables; preguntarlo en las entrevistas; plantilla de exportación solo si aparece un formato dominante |
| Competencia gratuita (Google Classroom) | No competir en funciones; competir en ponderación, boletas y simplicidad en español |

---

## Próximos pasos inmediatos

1. Docker Compose, settings divididos y CI.
2. App `organizations`, `Membership` y migración de datos de usuarios actuales.
3. Managers `for_organization`, middleware y prueba de aislamiento entre organizaciones.
4. Entrevistas con 10–15 docentes en paralelo; sus respuestas ajustan el Sprint 1. Preguntar siempre: "¿a dónde subes las calificaciones al final del periodo y qué formato e identificador del alumno te piden?" y "¿qué haces con tus grupos cuando termina el ciclo?".
5. Tramitar cuentas de Mercado Pago/Conekta y revisar requisitos de CFDI.
