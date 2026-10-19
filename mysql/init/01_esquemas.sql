-- Las tres capas de la base, cada una en su propio esquema:
--   crudo:    lo que responde la API, tal cual.
--   limpio:   los mismos datos, ordenados en tablas.
--   analisis: vistas listas para el dashboard.
-- utf8mb4 para que quepan nombres como "Côte d'Ivoire". La comparación distingue mayúsculas
-- y acentos, así dos textos distintos nunca cuentan como iguales.

CREATE DATABASE crudo    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;
CREATE DATABASE limpio   CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;
CREATE DATABASE analisis CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;
