-- Fichas de los indicadores del proyecto.
-- El nombre es el que da la API de la OMS. La definición es un resumen de la que publica la OMS
-- en la página del indicador (url_metodologia), donde está el texto completo.
-- De estos tres, solo la mortalidad materna tiene meta numérica en los ODS: menos de 70 muertes
-- por cada 100 000 nacidos vivos en el mundo para 2030.

INSERT INTO limpio.indicadores
  (codigo, nombre, unidad, tipo_dato, definicion, organizacion, url_metodologia, direccion_deseable, meta)
VALUES
  ('MDG_0000000026',
   'Maternal mortality ratio (per 100 000 live births)',
   'Deaths per 100 000 live births',
   'ESTIMACION',
   'Number of maternal deaths per 100 000 live births in the same period.',
   'WHO, UNICEF, UNFPA, World Bank Group and UNDESA/Population Division (UN MMEIG)',
   'https://www.who.int/data/gho/data/indicators/indicator-details/GHO/maternal-mortality-ratio-(per-100-000-live-births)',
   'BAJAR',
   70),

  ('MDG_0000000025',
   'Births attended by skilled health personnel (%)',
   '%',
   'REPORTADO',
   'Percentage of births attended by skilled health personnel, such as doctors, nurses or midwives.',
   'UNICEF and WHO',
   'https://www.who.int/data/gho/data/indicators/indicator-details/GHO/births-attended-by-skilled-health-personnel-(-)',
   'SUBIR',
   NULL),

  ('WHS4_154',
   'Antenatal care coverage - at least four visits (%)',
   '%',
   'REPORTADO',
   'Percentage of women aged 15-49 with a live birth who received antenatal care four or more times, from any provider.',
   'WHO',
   'https://www.who.int/data/gho/data/indicators/indicator-details/GHO/antenatal-care-coverage-at-least-four-visits',
   'SUBIR',
   NULL);
