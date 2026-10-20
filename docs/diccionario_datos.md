# Diccionario de datos

Qué guarda la base de datos, columna por columna, y de dónde sale cada valor.

La base tiene tres capas, cada una en su propio esquema de MySQL:

| Esquema | Qué guarda |
|---|---|
| `crudo` | Cada consulta a la API de la OMS y la respuesta tal como llegó. |
| `limpio` | Los mismos datos de la OMS, ordenados en tablas. |
| `analisis` | Vistas listas para usar. No guardan datos: los leen de `limpio` en el momento. |

El recolector escribe en `crudo` y `limpio`. El dashboard solo puede leer las vistas de `analisis`.

Para leer este documento:

- Todas las fechas están en hora UTC y con milisegundos (`DATETIME(3)`).
- Los textos usan utf8mb4, así caben nombres como "Curaçao" o "Türkiye". Al comparar textos se distinguen
  mayúsculas y acentos.
- Los nombres y los valores se guardan como los publica la OMS, en inglés y sin redondear. El proyecto no
  los traduce ni los corrige.
- La columna "Viene de" dice de qué campo de la respuesta de la API sale el valor. Una raya (—) quiere
  decir que lo pone el propio proyecto.

## Capa `crudo`

### `crudo.cargas`

Una fila por cada consulta a la API. En cada ciclo del recolector hay tres cargas de catálogos (regiones,
países y total mundial) y una por cada indicador.

| Columna | Tipo | Qué guarda | Viene de |
|---|---|---|---|
| `id` | INT UNSIGNED, llave primaria | Número de la carga. | — |
| `indicador_codigo` | VARCHAR(50), puede ir vacío | El indicador que se pidió, por ejemplo `MDG_0000000026`. Vacío en las cargas de catálogos. | — |
| `url_consulta` | VARCHAR(2000) | La dirección exacta que se le pidió a la API. | — |
| `inicio` | DATETIME(3) | Cuándo empezó la carga. | — |
| `fin` | DATETIME(3), puede ir vacío | Cuándo terminó. Vacío mientras la carga sigue en curso. | — |
| `recibidos` | INT UNSIGNED | Registros que trajo la respuesta. | — |
| `nuevos` | INT UNSIGNED | Registros que no estaban y se agregaron. | — |
| `cambiados` | INT UNSIGNED | Registros que la OMS cambió y se actualizaron. | — |
| `omitidos` | INT UNSIGNED | Registros que no pasaron las reglas de calidad. No se pierden: siguen en la respuesta original. | — |
| `estado` | ENUM (EN_CURSO, OK, ERROR) | Cómo va o cómo terminó la carga. | — |
| `mensaje` | TEXT, puede ir vacío | El motivo del error o el resumen de los omitidos. | — |

- Una carga que terminó (OK o ERROR) siempre tiene `fin`, y el `fin` no puede ser antes del `inicio`.
- Si el recolector se detiene a media carga, al empezar el siguiente ciclo esa carga pasa a ERROR con el
  mensaje "Interrumpida: el recolector se detuvo antes de terminar."
- Ejemplo real: la primera carga de la mortalidad materna dio recibidos 7,878, nuevos 7,878, cambiados 0 y
  omitidos 0. Las siguientes dieron nuevos 0 y cambiados 0, porque la OMS no había cambiado nada.

### `crudo.respuestas_api`

La respuesta de la API exactamente como llegó, una por carga (si la API no respondió, no hay).

| Columna | Tipo | Qué guarda | Viene de |
|---|---|---|---|
| `id` | INT UNSIGNED, llave primaria | Número de la respuesta. | — |
| `carga_id` | INT UNSIGNED, llave foránea a `cargas.id` | La carga a la que pertenece. | — |
| `cuerpo` | LONGTEXT | El JSON completo, sin ningún cambio. | Toda la respuesta |
| `recibido_en` | DATETIME(3) | Cuándo se guardó. | — |

- Va como texto y no con el tipo JSON de MySQL, porque ese tipo reordena el contenido. Una regla revisa que
  sea un JSON válido.
- Se guarda en su propia transacción: si después algo falla, la respuesta se queda.
- Cada ciclo guarda unos 7 MB: 4.6 MB de la mortalidad materna, 2.1 MB de los partos atendidos y menos de
  40 KB de los catálogos.

## Capa `limpio`

### `limpio.ubicaciones`

Países, regiones y total mundial, con el código y el nombre que les da la OMS. Al 19/10/2026 tenía 234
países, 43 regiones (entre ellas las 6 de la OMS) y el total mundial.

| Columna | Tipo | Qué guarda | Viene de |
|---|---|---|---|
| `codigo` | VARCHAR(20), llave primaria | Código de la OMS: `MEX`, `AMR`, `GLOBAL`. | `Code` en los catálogos; `SpatialDim` en los datos |
| `tipo` | VARCHAR(30) | `COUNTRY`, `REGION` o `GLOBAL`. | El catálogo del que viene; `SpatialDimType` en los datos |
| `nombre` | VARCHAR(200), puede ir vacío | El nombre en inglés: "Mexico", "Americas", "Global". | `Title` |
| `region_codigo` | VARCHAR(20), puede ir vacío, llave foránea a `ubicaciones.codigo` | La región de la OMS a la que pertenece: México está en `AMR`. | `ParentCode`, cuando `ParentDimension` es REGION |

- Las 6 regiones de la OMS son `AFR` (Africa), `AMR` (Americas), `SEAR` (South-East Asia), `EUR` (Europe),
  `EMR` (Eastern Mediterranean) y `WPR` (Western Pacific).
- Si un indicador trae una ubicación que no está en los catálogos, se agrega solo con su código y su tipo.

### `limpio.indicadores`

La ficha de cada indicador. Las de los tres indicadores del proyecto están en `mysql/init/04_indicadores.sql`.
Si se agrega otro en el `.env`, el recolector crea su ficha solo con el código y el nombre de la OMS.

| Columna | Tipo | Qué guarda | Viene de |
|---|---|---|---|
| `codigo` | VARCHAR(50), llave primaria | `MDG_0000000026`, `MDG_0000000025` o `WHS4_154`. | `IndicatorCode` |
| `nombre` | VARCHAR(500) | El nombre oficial en inglés. En cada ciclo se revisa si la OMS lo cambió. | `IndicatorName`, del catálogo de indicadores |
| `unidad` | VARCHAR(100), puede ir vacío | "Deaths per 100 000 live births" o "%". | — |
| `tipo_dato` | ENUM (ESTIMACION, REPORTADO), puede ir vacío | Si es la estimación de un modelo o un dato reportado por encuestas y registros. | — |
| `definicion` | TEXT, puede ir vacío | Un resumen de la definición de la OMS. | — |
| `organizacion` | VARCHAR(300), puede ir vacío | Quién produce el dato. | — |
| `url_metodologia` | VARCHAR(500), puede ir vacío | La página de la OMS con la definición completa. | — |
| `direccion_deseable` | ENUM (BAJAR, SUBIR), puede ir vacío | Hacia dónde es bueno que vaya. | — |
| `meta` | DOUBLE, puede ir vacío | La meta de los ODS, si tiene. Solo la mortalidad materna tiene una: menos de 70. | — |

### `limpio.observaciones`

Un valor por indicador, ubicación, desagregación y año. Es la tabla principal: al 19/10/2026 tenía 7,878
datos de la mortalidad materna y 2,749 de los partos atendidos.

| Columna | Tipo | Qué guarda | Viene de |
|---|---|---|---|
| `id` | INT UNSIGNED, llave primaria | Número de la fila. | — |
| `indicador_codigo` | VARCHAR(50), llave foránea a `indicadores` | El indicador. | `IndicatorCode` |
| `ubicacion_codigo` | VARCHAR(20), llave foránea a `ubicaciones` | El país, la región o el mundo. | `SpatialDim` |
| `anio` | SMALLINT | El año del dato. | `TimeDim` |
| `periodo` | VARCHAR(50), puede ir vacío | El periodo que cubre el dato. Casi siempre es el mismo año; en algunas encuestas es un rango, como "2013-2015". | `TimeDimensionValue` |
| `desagregacion` | VARCHAR(255) | `TOTAL` si el dato no viene separado por sexo, edad u otro grupo. Si viene separado, pares "Tipo:valor" unidos con "\|". | `Dim1`, `Dim2` y `Dim3`, con sus tipos |
| `valor` | DOUBLE | El valor. | `NumericValue` |
| `valor_min` | DOUBLE, puede ir vacío | El límite bajo del rango de incertidumbre. | `Low` |
| `valor_max` | DOUBLE, puede ir vacío | El límite alto. | `High` |
| `fuente` | TEXT, puede ir vacío | El texto de la OMS sobre de dónde sale el dato (una encuesta, un registro). Se guarda tal cual, aunque traiga espacios de más o acentos perdidos. | `Comments` |
| `fecha_publicacion_oms` | DATETIME(3), puede ir vacío | Cuándo publicó la OMS este valor, pasado a UTC. | `Date` |
| `carga_id` | INT UNSIGNED, llave foránea a `crudo.cargas` | La carga que trajo esta versión del valor. | — |

- No puede haber dos filas con el mismo indicador, ubicación, desagregación y año. Al volver a cargar, una
  fila solo se actualiza si la OMS cambió algo.
- Reglas de calidad: `valor_min` ≤ `valor` ≤ `valor_max` y un año entre 1900 y 2100. Lo que no las cumple no
  entra: se cuenta en `cargas.omitidos` y sigue guardado en `crudo`.
- Ejemplo real, México 2021 en mortalidad materna: valor 103.877921, rango de 60.6342347 a 175.6905246 y sin
  fuente (las estimaciones del modelo no la traen). En partos atendidos, México 2021 vale 85.1, sin rango y
  con la fuente "PLISA Health Information Platform…".

### `limpio.observaciones_historial`

Las versiones anteriores de un valor cuando la OMS lo corrige. Se llena sola con el trigger
`observaciones_guardar_historial`, que guarda la versión anterior antes de cada cambio, pero solo si de verdad
cambió algo. Al 19/10/2026 estaba vacía: la OMS no había corregido ningún dato desde la primera carga.

| Columna | Tipo | Qué guarda |
|---|---|---|
| `id` | INT UNSIGNED, llave primaria | Número de la fila. |
| `observacion_id` | INT UNSIGNED, llave foránea a `observaciones.id` | El dato que cambió. |
| `periodo`, `valor`, `valor_min`, `valor_max`, `fuente`, `fecha_publicacion_oms` | Los mismos tipos que en `observaciones` | Lo que valían antes del cambio. |
| `carga_id` | INT UNSIGNED, llave foránea a `crudo.cargas` | La carga que había traído esa versión. |
| `reemplazado_en` | DATETIME(3) | Cuándo se reemplazó. |
| `reemplazado_por_carga_id` | INT UNSIGNED, llave foránea a `crudo.cargas` | La carga que trajo la versión nueva. |

## Capa `analisis` (vistas)

Es lo único que lee el dashboard. Las vistas no guardan nada: cada consulta lee `limpio` en ese momento.

### `analisis.v_series`

Cada dato, con lo que ayuda a ver cómo cambió. Trae las columnas de `limpio.observaciones` (menos `id` y
`carga_id`), el nombre, el tipo y la región de la ubicación (`ubicacion_nombre`, `ubicacion_tipo`,
`region_codigo`) y `fecha_carga`, que es el inicio de la carga que trajo el valor. Además calcula estas
columnas, comparando cada dato con el anterior de la misma serie (mismo indicador, ubicación y desagregación,
en orden de año):

| Columna | Qué calcula |
|---|---|
| `anio_anterior` | El año del dato anterior. No siempre es el año inmediato: hay series con huecos. |
| `valor_anterior` | El valor de ese dato anterior. |
| `cambio_pct` | El cambio en por ciento: 100 × (valor − valor_anterior) / valor_anterior. Vacío en el primer dato o si el anterior vale 0. |
| `ancho_rango_relativo` | Qué tan ancho es el rango comparado con el valor: (valor_max − valor_min) / valor. Vacío si no hay rango. |
| `cambio_fuente` | 1 si la fuente es distinta a la del dato anterior, 0 si es igual y vacío en el primer dato. Es una pista, no una certeza: a veces solo cambia cómo está escrita. |

- Ejemplo real, México en mortalidad materna: 2020 vale 61.5 (+41.9 % desde 2019), 2021 vale 103.9 (+69.0 %)
  y 2022 vale 45.4 (−56.2 %). En 2021 el `ancho_rango_relativo` es 1.108: el rango es más ancho que el propio
  valor.
- La vista no marca nada como raro. El umbral lo decide quien la usa; en el dashboard es "Cambio importante
  desde", con 25 % de inicio.

### `analisis.v_ultimo_dato`

Las mismas columnas de `v_series`, pero solo el dato más reciente de cada serie. Sirve para el mapa. Ejemplo
real: en mortalidad materna, México 2023 vale 42.1 y el mundo 2023 vale 197.3.

### `analisis.v_ubicaciones`

Las columnas de `limpio.ubicaciones` más `region_nombre`, el nombre de la región. Para México es "Americas".

### `analisis.v_indicadores`

La ficha de los indicadores que ya tienen datos, con lo que cubren:

| Columna | Qué guarda |
|---|---|
| Las 9 de `limpio.indicadores` | La ficha. |
| `observaciones` | Cuántos datos tiene. |
| `ubicaciones` | En cuántos lugares. |
| `anio_desde`, `anio_hasta` | El primer y el último año. |
| `ultima_publicacion_oms` | La fecha de publicación de la OMS más reciente entre sus datos. |

Ejemplo real: la mortalidad materna tiene 7,878 datos de 202 lugares (195 países, 6 regiones y el mundo), de
1985 a 2023, y su publicación más reciente en la OMS es del 10/04/2025.

El healthcheck de MySQL consulta esta vista para saber si la base ya está lista, así que no hay que
cambiarle el nombre.

### `analisis.v_ultima_carga`

La última carga de cada indicador y la del último catálogo. Trae las columnas de `crudo.cargas` (con `id`
como `carga_id`) y `ultima_carga_ok`: cuándo terminó la última carga de ese indicador que salió bien. El
dashboard la usa para mostrar la fecha de la última carga y para saber si llegaron datos nuevos.

## Columnas del CSV que baja el dashboard

La pestaña Datos baja un CSV con estas columnas, todas de `analisis.v_series` y con los valores completos,
sin redondear:

| En el CSV | En la base |
|---|---|
| Indicador | `indicador_codigo` |
| Ubicación | `ubicacion_nombre` |
| Código | `ubicacion_codigo` |
| Tipo | `ubicacion_tipo` |
| Año | `anio` |
| Periodo | `periodo` |
| Valor | `valor` |
| Mínimo | `valor_min` |
| Máximo | `valor_max` |
| Fuente (texto de la OMS) | `fuente` |
| Publicado por la OMS (UTC) | `fecha_publicacion_oms` |
| Cargado aquí (UTC) | `fecha_carga` |

## Tres fechas que no hay que confundir

- `anio`: el año al que corresponde el dato (`TimeDim`).
- `fecha_publicacion_oms`: cuándo publicó la OMS ese valor (`Date`).
- `fecha_carga` (o `cargas.inicio`): cuándo lo bajó este proyecto.

Por ejemplo, el dato de mortalidad materna de México 2023 lo publicó la OMS el 10/04/2025 y este proyecto lo
bajó el 19/10/2026 (hora UTC).
