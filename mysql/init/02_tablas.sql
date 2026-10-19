-- Tablas de las capas crudo y limpio. Todas las fechas van en UTC.

-- crudo: qué se le pidió a la API, cuándo y qué respondió.

-- Cada consulta a la API es una carga, con sus conteos y cómo terminó.
CREATE TABLE crudo.cargas (
  id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  indicador_codigo VARCHAR(50)   NULL,  -- sin llave foránea para no depender de limpio; vacío en el catálogo de países
  url_consulta     VARCHAR(2000) NOT NULL,
  inicio           DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  fin              DATETIME(3)   NULL,
  recibidos        INT UNSIGNED  NOT NULL DEFAULT 0,
  nuevos           INT UNSIGNED  NOT NULL DEFAULT 0,
  cambiados        INT UNSIGNED  NOT NULL DEFAULT 0,
  omitidos         INT UNSIGNED  NOT NULL DEFAULT 0,
  estado           ENUM('EN_CURSO', 'OK', 'ERROR') NOT NULL DEFAULT 'EN_CURSO',
  mensaje          TEXT          NULL,
  KEY idx_cargas_inicio (inicio),
  -- Una carga terminada siempre tiene hora de fin, y el fin no puede ser antes del inicio.
  CONSTRAINT ck_cargas_fin CHECK ((estado = 'EN_CURSO' AND fin IS NULL)
                               OR (estado <> 'EN_CURSO' AND fin IS NOT NULL)),
  CONSTRAINT ck_cargas_orden CHECK (fin IS NULL OR fin >= inicio)
);

-- La respuesta de la API exactamente como llegó. Va como texto y no con el tipo JSON de MySQL,
-- porque ese tipo reordena y reescribe el contenido.
CREATE TABLE crudo.respuestas_api (
  id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  carga_id    INT UNSIGNED NOT NULL,
  cuerpo      LONGTEXT     NOT NULL,
  recibido_en DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_respuestas_carga FOREIGN KEY (carga_id) REFERENCES crudo.cargas (id),
  CONSTRAINT ck_respuestas_json CHECK (JSON_VALID(cuerpo))
);

-- limpio: los mismos valores de la OMS, ordenados en tablas.

-- Países, regiones y total mundial, con el código y el nombre que les da la OMS.
CREATE TABLE limpio.ubicaciones (
  codigo        VARCHAR(20)  PRIMARY KEY,  -- MEX, AMR, GLOBAL
  tipo          VARCHAR(30)  NOT NULL,     -- SpatialDimType: COUNTRY, REGION, GLOBAL
  nombre        VARCHAR(200) NULL,         -- vacío si la OMS no lo da
  region_codigo VARCHAR(20)  NULL,         -- región de la OMS a la que pertenece
  CONSTRAINT fk_ubicaciones_region FOREIGN KEY (region_codigo) REFERENCES limpio.ubicaciones (codigo)
);

-- Ficha de cada indicador. Las del proyecto están en 04_indicadores.sql; si llega uno nuevo,
-- el recolector lo agrega con el nombre que da la OMS y lo demás vacío.
CREATE TABLE limpio.indicadores (
  codigo             VARCHAR(50)  PRIMARY KEY,
  nombre             VARCHAR(500) NOT NULL,
  unidad             VARCHAR(100) NULL,
  tipo_dato          ENUM('ESTIMACION', 'REPORTADO') NULL,  -- estimación de un modelo o dato reportado
  definicion         TEXT         NULL,
  organizacion       VARCHAR(300) NULL,                     -- quién produce el dato
  url_metodologia    VARCHAR(500) NULL,
  direccion_deseable ENUM('BAJAR', 'SUBIR') NULL,           -- hacia dónde es bueno que vaya
  meta               DOUBLE       NULL                      -- meta de los ODS, si tiene
);

-- Un valor por indicador, ubicación, desagregación y año.
CREATE TABLE limpio.observaciones (
  id                    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  indicador_codigo      VARCHAR(50)  NOT NULL,
  ubicacion_codigo      VARCHAR(20)  NOT NULL,
  anio                  SMALLINT     NOT NULL,                  -- TimeDim
  periodo               VARCHAR(50)  NULL,                      -- TimeDimensionValue: casi siempre el año; en encuestas puede ser "2013-2015"
  desagregacion         VARCHAR(255) NOT NULL DEFAULT 'TOTAL',  -- 'TOTAL' o pares "Tipo:valor" unidos con "|"
  valor                 DOUBLE       NOT NULL,                  -- NumericValue
  valor_min             DOUBLE       NULL,                      -- Low
  valor_max             DOUBLE       NULL,                      -- High
  fuente                TEXT         NULL,                      -- Comments
  fecha_publicacion_oms DATETIME(3)  NULL,                      -- Date, pasada a UTC
  carga_id              INT UNSIGNED NOT NULL,                  -- carga que trajo esta versión del valor
  UNIQUE KEY uq_observaciones (indicador_codigo, ubicacion_codigo, desagregacion, anio),
  KEY idx_observaciones_mapa (indicador_codigo, anio),
  CONSTRAINT fk_observaciones_indicador FOREIGN KEY (indicador_codigo) REFERENCES limpio.indicadores (codigo),
  CONSTRAINT fk_observaciones_ubicacion FOREIGN KEY (ubicacion_codigo) REFERENCES limpio.ubicaciones (codigo),
  CONSTRAINT fk_observaciones_carga FOREIGN KEY (carga_id) REFERENCES crudo.cargas (id),
  -- Reglas de calidad. Lo que no las cumple no entra: se cuenta en omitidos y sigue guardado en crudo.
  CONSTRAINT ck_observaciones_anio CHECK (anio BETWEEN 1900 AND 2100),
  CONSTRAINT ck_observaciones_rango CHECK ((valor_min IS NULL OR valor_min <= valor)
                                       AND (valor_max IS NULL OR valor <= valor_max))
);

-- Versiones anteriores de un valor cuando la OMS lo corrige. La llena el trigger de abajo.
CREATE TABLE limpio.observaciones_historial (
  id                       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  observacion_id           INT UNSIGNED NOT NULL,
  periodo                  VARCHAR(50)  NULL,
  valor                    DOUBLE       NOT NULL,
  valor_min                DOUBLE       NULL,
  valor_max                DOUBLE       NULL,
  fuente                   TEXT         NULL,
  fecha_publicacion_oms    DATETIME(3)  NULL,
  carga_id                 INT UNSIGNED NOT NULL,  -- carga que había traído esta versión
  reemplazado_en           DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  reemplazado_por_carga_id INT UNSIGNED NOT NULL,  -- carga que trajo la versión nueva
  KEY idx_historial_observacion (observacion_id),
  CONSTRAINT fk_historial_observacion FOREIGN KEY (observacion_id) REFERENCES limpio.observaciones (id),
  CONSTRAINT fk_historial_carga FOREIGN KEY (carga_id) REFERENCES crudo.cargas (id),
  CONSTRAINT fk_historial_reemplazo FOREIGN KEY (reemplazado_por_carga_id) REFERENCES crudo.cargas (id)
);

-- Antes de cambiar un valor, guarda la versión anterior, pero solo si de verdad cambió algo.
DELIMITER $$
CREATE TRIGGER limpio.observaciones_guardar_historial
BEFORE UPDATE ON limpio.observaciones
FOR EACH ROW
BEGIN
  IF NOT (OLD.periodo <=> NEW.periodo
          AND OLD.valor <=> NEW.valor
          AND OLD.valor_min <=> NEW.valor_min
          AND OLD.valor_max <=> NEW.valor_max
          AND OLD.fuente <=> NEW.fuente
          AND OLD.fecha_publicacion_oms <=> NEW.fecha_publicacion_oms) THEN
    INSERT INTO limpio.observaciones_historial
      (observacion_id, periodo, valor, valor_min, valor_max, fuente, fecha_publicacion_oms,
       carga_id, reemplazado_por_carga_id)
    VALUES
      (OLD.id, OLD.periodo, OLD.valor, OLD.valor_min, OLD.valor_max, OLD.fuente,
       OLD.fecha_publicacion_oms, OLD.carga_id, NEW.carga_id);
  END IF;
END$$
DELIMITER ;
