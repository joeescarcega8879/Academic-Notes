# Academic Notes — Plan de producto e implementación

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
13. [Temario e IA asistida](#13-temario-e-ia-asistida)

---

## 1. Visión y propuesta de valor

**Frase de valor:** "Tu libreta de calificaciones, tus actividades y tu comunicación con alumnos, en un solo lugar y en 5 minutos de configuración."

**Nicho objetivo:** docentes de secundaria, preparatoria y universidad en México y Latinoamérica que hoy llevan calificaciones en Excel y necesitan ponderaciones, listas, boletas y actividades calificadas en un solo lugar, en español y sin curva de aprendizaje.

**Diferencia frente a la competencia:** Google Classroom es gratis pero no calcula promedios ponderados por criterio ni genera boletas; Moodle es potente pero requiere administración técnica. Academic Notes se posiciona como la herramienta simple que resuelve el flujo real del docente: lista → esquema de evaluación → actividades → calificar → boleta.

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

**Modelo de venta (decidido el 2026-10-14):** *product-led*, como Canva o Notion. La portada y la página de Precios son públicas y su acción principal es «Empezar gratis». El registro no pide tarjeta y deja al docente en el plan Gratis. El cobro vive **dentro de la app**: al tocar un límite el docente ve «Mejorar plan», y en Ajustes hay una pantalla «Plan y facturación». El pago se hace en la página alojada de la pasarela (la tarjeta nunca pasa por el servidor) y un webhook cambia el plan de la organización; cancelar o cambiar de plan se hace en el portal de la pasarela. Mientras el marketing no estorbe, la portada y Precios viven en el mismo proyecto Django y leen los planes de un solo lugar. Separarlos después (sitio de marketing en el dominio raíz, app en `app.`) solo cuesta cambiar enlaces.

**Principios de los planes:**

1. El plan Gratis debe dar el momento clave completo: importar la lista, armar el esquema ponderado y ver la calificación final en la libreta. Se limita la escala, no lo central.
2. Se paga donde se siente el valor: al fin del periodo (boletas) y cuando el docente crece (más grupos).
3. Los datos nunca quedan de rehén: nada se borra ni se bloquea para lectura, y el docente siempre puede exportar sus calificaciones.
4. Pocos límites, fáciles de contar y de explicar (grupos y alumnos), no una colección de microlímites.
5. Los alumnos nunca pagan ni ven límites.

**Planes** (nombres decididos el 2026-10-17: Gratis, Pro y Plus; Gratis y Pro se publican al lanzar y Plus cuando exista la primera función de IA):

| | Gratis | Pro | Plus |
|---|---|---|---|
| Precio | $0 | **$149 MXN/mes** · **$1,490 MXN/año** (2 meses gratis) | **$249 MXN/mes** · **$2,490 MXN/año** (hipótesis) |
| Grupos activos | 2 | Ilimitados | Ilimitados |
| Alumnos en grupos activos | 60 | Ilimitados (uso razonable) | Ilimitados (uso razonable) |
| Esquema ponderado, libreta, importar lista, código de invitación, mensajes, duplicar para nuevo ciclo | Sí | Sí | Sí |
| Tareas, proyectos, participación y exámenes | Sí | Sí | Sí |
| Temario por semanas (sección 13) | Sí | Sí | Sí |
| Quizzes autocalificables | Sí, **sin tiempo límite** | Sí, con tiempo límite | Sí, con tiempo límite |
| Banco de preguntas | Hasta 30 preguntas | Ilimitado | Ilimitado |
| Concentrado en Excel | Columnas fijas | Columnas a elegir y ordenar | Columnas a elegir y ordenar |
| Alumnos en riesgo | Sí | Sí | Sí |
| **Boletas en PDF** | Con marca de agua «Generado con Academic Notes» | Sin marca | Sin marca |
| **IA** (generar desde el temario y calificación asistida, sección 13) | No | No | Sí, con cuota mensual |

- **Boletas con marca de agua, no bloqueadas.** El docente gratis ve la boleta bien hecha; cuando tiene decenas que entregar y no quiere la marca, paga. Es el momento de mayor disposición a pagar, y la marca muestra el producto a padres y alumnos.
- **Nombres de los planes (decidido el 2026-10-17):** Gratis, Pro y Plus. El plan que se llamaba «Docente» (`Plan.TEACHER`, $149) se muestra como **Pro**, y `Plan.TEACHER_PLUS` como **Plus** (aplicado en el código el 2026-10-17). Las llaves internas no cambiaron: solo hay una migración de `choices`, sin tocar datos.
- **Plus = Pro + IA, con costo extra.** Incluye la IA del temario (generar tareas, quizzes y exámenes y calificación asistida; ver sección 13) con una cuota mensual de usos, y WhatsApp y almacenamiento ampliado cuando existan. Referencia $249 MXN/mes y $2,490 MXN/año (diez meses por doce, como Pro): hipótesis a ajustar con el costo real de la IA. **No se publica todavía:** se agrega cuando exista la primera función de IA; no se vende nada que no esté. Mientras tanto se asigna a mano desde el admin.
- **El plan anual** cobra 10 meses por 12 y es donde vive el margen. Si la pasarela lo permite, el anual puede pagarse en una sola exhibición con OXXO o SPEI. Un pase semestral (por los ciclos escolares) queda por evaluar, no decidido.
- **Los números son hipótesis iniciales.** Los topes (2 grupos, 60 alumnos y 30 preguntas) y los precios viven en una sola tabla (`services/limits.py`) y se ajustan con evidencia: conversión de Gratis a pago (sección 11) y uso real. Sin tope de almacenamiento por organización por ahora (10 MB por archivo en todos los planes): limitarlo exige medir el tamaño de cada archivo y se hará cuando haga falta.

**Cómo se comportan los límites:**

- Al llegar al tope solo se bloquea **crear**: un grupo nuevo, desarchivar uno, o agregar o importar alumnos que lo excedan. Lo que ya existe sigue funcionando.
- El mensaje es concreto: «Tu lista trae 75 alumnos; tu plan permite 60 y ya tienes 40», con un botón «Mejorar plan». Una importación que excede el tope se rechaza completa, no se corta a la mitad.
- Los grupos archivados no cuentan; desarchivar sí verifica el límite. Los alumnos se cuentan por ficha de lista en grupos activos, no por cuenta.
- Al cancelar el plan de pago, los grupos de más pasan a solo lectura (el docente elige cuáles quedan activos). Nada se borra. *Estado (2026-10-14):* esto se construye con la pasarela (paso 4 de la ruta); mientras tanto, estar por encima de un tope (por ejemplo, si el admin baja el plan a mano) deja todo activo y solo impide crear más, y la pantalla «Plan y facturación» lo explica.
- Si falla un cobro, hay 7 días de gracia antes de bajar de plan, alineados con los reintentos de la pasarela (también del paso 4).

**Dónde se engancha en el código:** un solo servicio con `check_limit(org, límite)` y `has_feature(org, función)`, sobre `Organization.plan`. Se aplica en `CourseCreateView` y `CourseUnarchiveView` (grupos), `StudentAddView` y `StudentImportView` (alumnos), la configuración del quiz (`time_limit_minutes`), el banco de preguntas (30), `TranscriptsView` (marca de agua) y `WorkbookConfigView` (columnas). Nunca condicionales por plan regados en las vistas (sección 7).

**Ruta hacia el cobro** (cada paso se publica sin esperar al siguiente):

1. Publicar gratis: registro y plan Gratis tal como están. Es donde más se aprende.
2. Página de Precios con los dos planes y el botón «Próximamente» del plan de pago (o lista de espera), para ver si se lee y qué plan llama la atención.
3. Límites funcionando sin cobrar: el módulo `limits`, los mensajes de «Mejorar plan» y la pantalla «Plan y facturación». El plan de pago se asigna a mano desde el admin.
4. Pasarela en modo de prueba: checkout, webhook y portal con tarjetas falsas, recorriendo el flujo completo, incluida la baja de plan y el fallo de cobro.
5. Cobro real, cuando existan dominio, datos fiscales (RFC), revisión legal de términos y privacidad, y respaldos probados. Pasar de prueba a real es cambiar las llaves.

**Números de referencia** (supuestos a verificar, no datos): una pasarela con tarjeta cobra del orden de 3.6 % + $3 MXN por cargo, de modo que de $149 quedan cerca de $140. La infraestructura en etapa temprana (servidor, base de datos, Redis, correo, respaldos) costaría del orden de $600–1,100 MXN al mes, así que el punto de equilibrio está en unos 5 a 8 docentes de pago. Ilustración: si 3 de cada 100 docentes gratis pagaran, con 200 docentes gratis se cubriría la infraestructura; ese porcentaje es una suposición.

### Edición Institución (cobro anual)

| Plan | Por alumno/año | Alternativa por docente/año | Incluye |
|---|---|---|---|
| Básico | $60–90 MXN | $2,000–2,500 MXN | Hasta 300 alumnos, panel director, reportes globales |
| Estándar | $90–140 MXN | $2,500–3,500 MXN | Hasta 1,500 alumnos, portal de padres, asistencia, soporte prioritario |
| Enterprise | Cotización (desde $30,000 MXN/año) | — | Ilimitado, SSO, capacitación, exportaciones personalizadas, SLA |

Estrategia de entrada: piloto gratuito de un periodo para las primeras 5 escuelas a cambio de testimonios.

**Instituciones no entran por autoservicio.** Hoy no existen el panel de dirección, el portal de padres ni la asistencia (Fase 2), así que **no se publican precios institucionales al lanzar**: la página de Precios ofrece «Hablar con ventas». El piloto gratuito se otorga asignando el plan a mano desde el admin, y el cobro es anual con factura manual (CFDI vía PAC) hasta que haya volumen que justifique automatizarlo.

### Decisiones abiertas del cobro

- **Pasarela:** por decidir. Recomendación: Stripe primero (Billing para suscripciones, OXXO/SPEI para el pago anual único, reintentos), con una capa de proveedor para sumar Mercado Pago o Conekta después.
- **Datos fiscales:** RFC y régimen de quien factura; CFDI requiere un PAC aparte.
- **Dominio** propio para el sitio, los correos de soporte y los remitentes (hoy son marcadores `@academicnotes.app`).
- **Pase semestral** y tope de «uso razonable» de alumnos de los planes Pro y Plus.
- **Revisión legal** de términos y aviso de privacidad antes de cobrar.

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
| 10 | Temario e IA asistida | Temario dividido por semanas; con IA, generar tareas, quizzes y exámenes desde el temario y calificar tareas con código anónimo, siempre con aprobación del docente (ver sección 13) | Temario: todos los planes; IA: plan Plus |

### Alumnos, matrícula y ciclos escolares

**El alumno de la lista no es la cuenta.** Al importar desde Excel los alumnos aún no tienen usuario, y muchos nunca lo tendrán (docentes que usan Academic Notes solo como libreta). Por eso existe `Student`, separado de `User`:

- `Student`: organización, matrícula, nombre(s), apellidos, correo opcional, `user` (FK nullable que se enlaza cuando el alumno usa el código de invitación).
- `Enrollment` apunta a `Student`, no a `User`.
- **Matrícula:** `CharField` opcional (nunca entero: hay ceros a la izquierda y letras). Única por organización cuando no está vacía. Vive en `Student` porque pertenece a la institución, no a la persona ni al curso.
- El importador lee la columna de matrícula **como texto** (Excel la convierte a número o notación científica) y la usa como **llave de re-importación** (upsert): subir la lista actualizada no duplica alumnos.
- Toda exportación (concentrado Excel, boleta) incluye la matrícula. El docente elige y ordena las columnas del concentrado, porque el formato que exige cada sistema de control escolar (SEP estatal, universidad) varía y no se intenta adivinar.
- CURP: solo si un docente la pide, y siempre opcional (dato personal de menores; ver sección 10).

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
- Fase 3: generación de tareas, quizzes y exámenes con IA a partir del temario y calificación asistida de tareas, siempre con aprobación del docente (sección 13); detección de plagio básica.

---

## 5. Arquitectura

### Backend

- **Django + Django REST Framework.** Apps: `organizations`, `accounts`, `courses`, `grades`, `activities`, `submissions`, `reports`, `messaging`, `billing`, `api`.
- **Multi-tenant por fila:** modelo `Organization`; todo modelo relevante lleva FK a ella. El docente individual es una organización de un solo miembro. No se usan esquemas separados por tenant al inicio.
- **`Membership`** (usuario, organización, rol: `owner`, `teacher`, `student`, `admin`, `coordinator`, `parent`). Un usuario puede tener roles distintos en organizaciones distintas.
- **Frontend web:** plantillas Django + HTMX/Alpine.js para el MVP. Migrar a un framework SPA solo si el constructor de exámenes lo exige.
- **Tareas asíncronas:** Celery + Redis (PDFs, correos, recordatorios, recálculos masivos, importaciones).
- **Archivos:** S3 o compatible (MinIO en local) desde el primer sprint que maneje entregas.
- **Pagos:** Mercado Pago o Conekta para México (tarjeta, OXXO, SPEI); Stripe para el resto de LATAM. CFDI vía PAC (Facturama u otro). La pasarela está por decidir (ver «Decisiones abiertas del cobro», sección 2).
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
syllabus → courses (las actividades pueden enlazar a una semana del temario)
ai → syllabus, actividades, entregas, quizzes (usa sus servicios; ninguna otra app depende de `ai`)
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

**Criterio de listo:** un docente se registra, importa su lista, configura ponderación, crea tarea y quiz, califica, descarga boletas y paga sin intervención manual. El cobro se activa al final, siguiendo la «Ruta hacia el cobro» de la sección 2. Correos transaccionales vía Celery. Desplegado con respaldos probados antes del primer cobro.

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
- Temario por semanas e IA asistida: generar tareas, quizzes y exámenes desde el temario y calificar tareas con código anónimo, con aprobación obligatoria del docente. Diseño y entregas en la sección 13.
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
5. **Límites de plan centralizados** en `check_limit(org, límite)` y `has_feature(org, función)` (`services/limits.py`); nunca condicionales por plan regados en vistas. Los cursos archivados no cuentan contra el límite; desarchivar sí lo verifica.
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
- **IA y datos de alumnos:** solo el nivel de pago del proveedor (el gratuito puede usar el contenido para mejorar sus productos); no se envían nombre, matrícula, correo ni CURP; el aviso de privacidad y el contrato con las escuelas nombran al proveedor y la transferencia; la organización puede desactivar la IA (sección 13).
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
| Conversión | Gratis → pago | Valida precio y límites del plan gratis; con ella se ajustan los topes de la sección 2 |
| Churn mensual | Suscripciones canceladas / activas | > 5 % → investigar |
| Alumnos activos por docente | Alumnos que entregan o consultan al menos una vez por semana | Mide adopción real |
| Tiempo para calificar | Minutos desde abrir la bandeja hasta cerrar una actividad | Guía del diseño de la app móvil |
| NPS | Encuesta trimestral | — |
| Aprobación de propuestas de IA | Propuestas aprobadas sin cambios / propuestas generadas | Muy baja → la calidad no sirve; muy alta → ¿el docente revisa de verdad? |

---

## 12. Riesgos

| Riesgo | Mitigación |
|---|---|
| Ciclo escolar: instituciones deciden mayo–julio y diciembre–enero | Tener piloto listo antes de esas ventanas |
| Soporte y capacitación consumen tiempo | Cobrarlos aparte o incluirlos solo en Enterprise |
| El módulo de exámenes se traga meses | MVP solo con opción múltiple y verdadero/falso |
| Un solo desarrollador | 15–20 h/semana sostenidas; no cambiar de stack a medio camino; móvil solo después de Fase 1 |
| Mantener web y móvil sincronizadas | Toda lógica en servicios; API versionada; app declara versión mínima de API |
| No se conoce el formato que exige el sistema de control escolar de cada docente (SEP estatal, universidad) | Exportación con matrícula y columnas configurables; plantilla de exportación solo si aparece un formato dominante |
| La IA inventa una pregunta, una clave o una calificación incorrecta | Todo sale ligado al temario con cita del tema, pasa por esquema y validaciones, y **nada llega al alumno sin aprobación del docente**; la calificación sugerida no se guarda hasta que el docente la confirma (sección 13) |
| Costo de la IA se dispara | Cuota mensual por plan, registro de uso y costo por organización, modelos ligeros por defecto, lotes y caché |
| Competencia gratuita (Google Classroom) | No competir en funciones; competir en ponderación, boletas y simplicidad en español |

---

## 13. Temario e IA asistida

> **Estado (2026-10-17):** diseño con las decisiones del desarrollador incorporadas (al final de la sección), nada construido. Reúne tres ideas del desarrollador: subir el temario y dividirlo por semanas; generar tareas, quizzes y exámenes con IA **a partir de ese temario**; y calificar tareas sin que el nombre del alumno viaje a la IA, usando un código anónimo. La regla que ordena todo: **la IA propone, el docente decide.** Las decisiones abiertas están al final.

### Temario y semanas (no usa IA)

El temario es útil por sí solo y es la base de lo demás, así que se construye primero.

- **Subir:** el docente sube su temario (PDF, Word o texto pegado) a un grupo. El archivo original queda privado, igual que las entregas, y el texto se extrae en Celery. Un PDF escaneado sin texto no se puede leer sin IA: se ofrece pegar el texto.
- **Dividir por semanas:** una lista editable de semanas (`SyllabusWeek`: número, título, temas y objetivos, fecha de inicio ajustable). El docente puede agregar, dividir, unir y mover temas, y marcar semanas sin clase. La IA puede **proponer** la división (sección «Generación»), pero el editor manual siempre existe y siempre manda.
- **Enlazar:** una actividad puede apuntar a una semana (FK opcional). Con eso hay una vista de planeación: qué semana toca, qué actividades faltan por crear y cuáles cubren cada tema.
- **Solo del docente (decidido):** el alumno no ve el temario. Es material de planeación del docente y de insumo para la IA.
- **Alcance:** app nueva `syllabus`, que depende de `courses`. Duplicar un grupo para un nuevo ciclo copia el temario (sin fechas), igual que las actividades.

### Generación con IA a partir del temario

| Se genera | Qué produce | Dependencia |
|---|---|---|
| División del temario | Propuesta de semanas y temas a partir del texto subido | Temario |
| Tarea | Título, instrucciones, criterios de calificación (o rúbrica, cuando existan) y puntos | Temario |
| Quiz | Preguntas de opción múltiple y verdadero/falso con clave, explicación y etiqueta de tema (lo que ya soporta el constructor) | Temario, Sprint 4 |
| Examen | Conjunto de preguntas para el tipo examen, con ventana y tiempo estricto | Temario, Fase 2 (sprint 6) |

- **Siempre ligada al temario.** El docente elige una o varias semanas, el tipo, la cantidad y la dificultad. A la IA solo se le envía el texto de esas semanas y se le pide que no use conocimiento externo. Cada pregunta o tarea cita el tema del temario que cubre; si no puede citarlo, se descarta.
- **Salida estricta.** La respuesta debe cumplir un esquema (JSON validado) y pasar las mismas validaciones del constructor: una sola respuesta correcta, opciones sin duplicados, puntos válidos. Se avisa si una pregunta se parece a otra del banco.
- **Pasa por Celery.** Es lento y puede fallar: se encola, se reintenta con tope y se muestra el estado («generando…»). Nunca bloquea la petición del docente.

### Aprobación obligatoria

Nada generado por IA llega a un alumno sin **dos acciones del docente**: aprobar y publicar.

1. La IA deja **propuestas** (`AIDraft`: tipo, contenido, semana de origen, estado `propuesta`). No son actividades ni preguntas todavía.
2. El docente las revisa, edita, regenera o descarta una por una. En un quiz ve la clave y la explicación de cada pregunta.
3. Al **aprobar**, se crea la actividad o las preguntas como **borrador** con origen `ia`, quién aprobó y cuándo (mismo espíritu que `GradeHistory`).
4. **Publicar** sigue siendo el paso de siempre. No existe publicación automática.

### Código anónimo y calificación asistida de tareas

**Para qué sirve.** (a) Que el nombre, la matrícula y el correo del alumno no viajen a la IA. (b) Que el servidor pueda **identificar solo** de quién es un documento cuando el docente sube un lote de PDFs o escaneos (tareas en papel, entregas por correo o por otro medio). Las entregas hechas desde el portal ya saben de quién son por la cuenta; ahí el código solo evita que el nombre aparezca dentro del documento.

**Cómo funciona.**

- `StudentCode`: alumno (uno por `Student`) y un `uuid` (UUID v4, no secuencial) que es la llave interna. Al alumno se le muestra una **versión corta** legible (8 caracteres sin letras ambiguas, más un dígito de control), única por organización. Ejemplo: `K7M2-QX9D`. Un UUID completo de 36 caracteres es impráctico de escribir a mano.
- **Un código fijo por alumno (decidido):** lo aprende una vez y lo usa en todas sus tareas. Se muestra en su perfil («Mi código») y en la lista del docente, y el docente puede imprimir una **hoja de códigos del grupo** (PDF) para entregas en papel. El alumno lo escribe **en lugar de su nombre**.
- **Costo de que sea fijo:** el proveedor de IA ve el mismo código en varias tareas del mismo alumno (un seudónimo estable, sin nombre, y sin la tabla que lo liga a la persona), y un compañero podría copiar un código. Se mitiga así: el docente puede **regenerar** el código de un alumno (si se filtra, o al cambiar de ciclo); en las entregas por el portal manda la cuenta y, si el código del documento no coincide, se marca; y en un lote, dos archivos con el mismo código en una actividad van a la cola «Sin identificar».
- **La tabla código ↔ alumno nunca sale del servidor.** A la IA solo llega el código y el contenido.

**Identificar un lote.** Por cada archivo se extrae el texto y se busca el código; el dígito de control atrapa errores de lectura de letra manuscrita. Una coincidencia única se asigna sola. Si no hay código, hay dos iguales, o no corresponde a nadie, el archivo va a una cola **«Sin identificar»** con vista previa para asignarlo a mano. En escaneos sin texto, leer el código con un modelo de visión cuesta algo; el docente decide si lo usa o asigna a mano.

**Calificación asistida.** Con la tarea identificada, la IA recibe las instrucciones, los criterios y el contenido, y devuelve por criterio una **calificación sugerida, la cita textual de la entrega que la sustenta y un comentario**. En la bandeja el docente ve el documento junto a la sugerencia, la edita y la **confirma**. Solo al confirmar se crea la calificación (con `GradeHistory` marcando «sugerida por IA, confirmada por»). El alumno no ve nada antes de esa confirmación. Se descarta el uso de la «confianza» que el modelo dice tener, porque no es fiable: lo que se muestra es la evidencia.

**Confirmar en bloque (decidido el 2026-10-17).** Con muchas entregas, confirmar una por una no es práctico, así que existe el botón «Confirmar las sugeridas sin cambios (N)», con estas reglas: solo incluye entregas identificadas, con evidencia en cada criterio y sin advertencias (excluye las vacías, ilegibles o «Sin identificar»); antes de aplicar muestra un resumen (cuántas, promedio y distribución) y pide confirmación; cada nota queda en `GradeHistory` como «sugerida por IA, confirmada en bloque por…», y se corrige después como cualquier otra. El docente puede abrir cualquier entrega antes de confirmar.

**Honestidad sobre el código:** reduce los datos personales que se envían, no los elimina. Un alumno puede escribir su nombre dentro del texto o una letra manuscrita puede identificarlo. Por eso, además, se quitan del texto antes de enviarlo el nombre, la matrícula y el correo conocidos del grupo, y siguen siendo necesarios el nivel de pago del proveedor y los textos legales de abajo.

### Privacidad y control

- **Solo nivel de pago del proveedor.** En el nivel gratuito de Gemini, Google puede usar el contenido para mejorar sus productos; en el de pago no. Nunca se usa el gratuito con datos de alumnos.
- **Minimizar:** no se envía nombre, matrícula, correo ni CURP. Se envía el código y el contenido.
- **Aviso de privacidad y contrato** con las escuelas deben nombrar al proveedor de IA y la transferencia (se suma a la revisión legal pendiente de la sección 10).
- **Interruptor por organización:** una escuela o un docente puede **desactivar** la IA. Sin consentimiento, no se envía nada.
- **Registro de uso** (`AIRequest`): organización, usuario, tipo, modelo, tokens y costo. No guarda el contenido enviado más allá de lo necesario para auditar, con retención corta.
- **Capa de proveedor** (`ai/providers/`): una interfaz y Gemini como primera implementación, para poder cambiar de proveedor. La clave de API vive solo en el servidor.

### Costo y plan

Precios de lista de Gemini a octubre de 2026, **por verificar en ai.google.dev** antes de decidir: Flash-Lite ≈ $0.30 de entrada y $2.50 de salida por millón de tokens, Flash ≈ $0.75 y $3.75 (precio de introducción hasta el 31 de diciembre de 2026; después $1.50 y $7.50), Pro ≈ $2 y $12. La API por lotes cuesta la mitad y el caché de contexto abarata la entrada repetida.

Estimaciones (supuestos, no mediciones): generar 20 preguntas cuesta del orden de $0.01 a $0.04 USD según el modelo; revisar una tarea de 5 páginas, unos $0.005 USD con Flash (supone unos 258 tokens por página, cifra anterior que no se ha verificado). Un docente con 3 grupos de 30 alumnos y 4 tareas al mes serían 360 revisiones, del orden de $1.80 USD al mes. Las fotos de hojas escritas a mano cuestan más.

- **Va en Plus, con costo extra (decidido el 2026-10-17).** Plus es Pro más IA: referencia $249 MXN/mes, unos $100 por encima de Pro. Esa diferencia cubre con holgura el costo de un uso intenso (unos $35 MXN al mes con la estimación de arriba, a un tipo de cambio de unos 19 MXN por dólar que no se ha verificado). Se publica cuando exista la primera función de IA (sección 2). Gratis y Pro no incluyen IA.
- **Cuota mensual de uso de IA en Plus**, con `check_limit` / `has_feature` (sección 7): se mide en usos (generaciones y revisiones), no en tokens, y la cifra se ajusta con el costo real.
- **El temario sin IA va en todos los planes (decidido):** no cuesta y retiene.
- Se empieza con Flash-Lite o Flash; Pro solo si la calidad de los exámenes lo exige.

### Entregas propuestas

| Entrega | Contenido | Depende de |
|---|---|---|
| T1 | Temario y semanas (sin IA): subir, extraer texto, editor de semanas, enlazar actividades | — |
| T2 | Capa de IA: proveedor, cuotas por plan, `AIRequest`, interruptor por organización, aviso legal | Revisión legal |
| T3 | IA para proponer la división del temario y generar preguntas de quiz, con aprobación | T1, T2, Sprint 4 |
| T4 | IA para tareas y exámenes con aprobación | T3; exámenes: Fase 2 |
| T5 | Código anónimo, carga de lotes e identificación (**sirve sin IA**), y calificación asistida | T2; rúbricas mejoran el resultado (Fase 2) |

Cada entrega se publica sola. T1 y la parte de identificación de T5 aportan valor aunque nunca se active la IA.

### Decisiones tomadas y abiertas

**Decididas el 2026-10-17:**

- Código **fijo por alumno**, en versión corta con dígito de control y un UUID como llave interna.
- El alumno **no ve** el temario.
- El temario va en **todos los planes**.
- Se puede **confirmar en bloque** las calificaciones sugeridas, con las reglas de arriba.
- La IA se cobra aparte: tres planes, **Gratis, Pro y Plus**, y la IA solo en Plus.

**Abiertas:**

- Precio final de Plus y cuota mensual de usos (hoy hipótesis: $249 MXN/mes, $2,490 MXN/año; la cuota sale del costo real).
- Qué más trae Plus además de la IA, cuando existan WhatsApp y almacenamiento ampliado.
- Proveedor: Gemini primero por costo; la capa de proveedor permite cambiarlo.

---

## Próximos pasos inmediatos

1. Docker Compose, settings divididos y CI.
2. App `organizations`, `Membership` y migración de datos de usuarios actuales.
3. Managers `for_organization`, middleware y prueba de aislamiento entre organizaciones.
4. Tramitar cuentas de Mercado Pago/Conekta y revisar requisitos de CFDI.
