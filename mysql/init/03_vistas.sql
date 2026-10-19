-- Vistas de la capa analisis: es lo único que lee el dashboard.
-- Corren con los permisos de quien las creó (SQL SECURITY DEFINER); así el usuario
-- dashboard puede leer los datos sin tener acceso a las tablas.

-- Cada serie año por año, con lo que ayuda a encontrar cosas raras.
-- No marca nada como anomalía: el umbral lo decide quien la usa.
CREATE SQL SECURITY DEFINER VIEW analisis.v_series AS
SELECT
  o.indicador_codigo,
  o.ubicacion_codigo,
  u.nombre AS ubicacion_nombre,
  u.tipo   AS ubicacion_tipo,
  u.region_codigo,
  o.desagregacion,
  o.anio,
  o.valor,
  o.valor_min,
  o.valor_max,
  o.fuente,
  o.fecha_publicacion_oms,
  c.inicio AS fecha_carga,
  -- El dato anterior puede no ser del año inmediato anterior: hay series con huecos.
  LAG(o.anio)  OVER serie AS anio_anterior,
  LAG(o.valor) OVER serie AS valor_anterior,
  100 * (o.valor - LAG(o.valor) OVER serie) / NULLIF(LAG(o.valor) OVER serie, 0) AS cambio_pct,
  -- Qué tan ancho es el rango de incertidumbre comparado con el valor.
  (o.valor_max - o.valor_min) / NULLIF(o.valor, 0) AS ancho_rango_relativo,
  -- 1 si la fuente cambió respecto al dato anterior: un cambio de fuente puede parecer tendencia.
  CASE
    WHEN LAG(o.anio) OVER serie IS NULL THEN NULL
    WHEN o.fuente <=> LAG(o.fuente) OVER serie THEN 0
    ELSE 1
  END AS cambio_fuente
FROM limpio.observaciones o
JOIN limpio.ubicaciones u ON u.codigo = o.ubicacion_codigo
JOIN crudo.cargas c ON c.id = o.carga_id
WINDOW serie AS (PARTITION BY o.indicador_codigo, o.ubicacion_codigo, o.desagregacion ORDER BY o.anio);

-- El dato más reciente de cada serie, con su año (para el mapa).
CREATE SQL SECURITY DEFINER VIEW analisis.v_ultimo_dato AS
SELECT
  indicador_codigo, ubicacion_codigo, ubicacion_nombre, ubicacion_tipo, region_codigo,
  desagregacion, anio, valor, valor_min, valor_max, fuente, fecha_publicacion_oms, fecha_carga,
  anio_anterior, valor_anterior, cambio_pct, ancho_rango_relativo, cambio_fuente
FROM (
  SELECT s.*,
         ROW_NUMBER() OVER (PARTITION BY s.indicador_codigo, s.ubicacion_codigo, s.desagregacion
                            ORDER BY s.anio DESC) AS orden
  FROM analisis.v_series s
) series
WHERE orden = 1;

-- Países, regiones y total mundial, con el nombre de su región.
CREATE SQL SECURITY DEFINER VIEW analisis.v_ubicaciones AS
SELECT u.codigo, u.nombre, u.tipo, u.region_codigo, r.nombre AS region_nombre
FROM limpio.ubicaciones u
LEFT JOIN limpio.ubicaciones r ON r.codigo = u.region_codigo;

-- Los indicadores que ya tienen datos, con su ficha y qué tanto cubren.
-- El healthcheck de compose.yaml consulta esta vista: no cambiarle el nombre.
CREATE SQL SECURITY DEFINER VIEW analisis.v_indicadores AS
SELECT
  i.codigo, i.nombre, i.unidad, i.tipo_dato, i.definicion, i.organizacion,
  i.url_metodologia, i.direccion_deseable, i.meta,
  COUNT(*)                           AS observaciones,
  COUNT(DISTINCT o.ubicacion_codigo) AS ubicaciones,
  MIN(o.anio)                        AS anio_desde,
  MAX(o.anio)                        AS anio_hasta,
  MAX(o.fecha_publicacion_oms)       AS ultima_publicacion_oms
FROM limpio.indicadores i
JOIN limpio.observaciones o ON o.indicador_codigo = i.codigo
GROUP BY i.codigo;

-- La última carga de cada indicador (la del catálogo de países tiene el indicador vacío)
-- y cuándo terminó la última que salió bien.
CREATE SQL SECURITY DEFINER VIEW analisis.v_ultima_carga AS
SELECT
  c.indicador_codigo, c.id AS carga_id, c.estado, c.inicio, c.fin,
  c.recibidos, c.nuevos, c.cambiados, c.omitidos, c.mensaje, c.url_consulta,
  (SELECT MAX(ok.fin)
     FROM crudo.cargas ok
    WHERE ok.estado = 'OK' AND ok.indicador_codigo <=> c.indicador_codigo) AS ultima_carga_ok
FROM crudo.cargas c
WHERE c.id IN (SELECT MAX(id) FROM crudo.cargas GROUP BY indicador_codigo);
