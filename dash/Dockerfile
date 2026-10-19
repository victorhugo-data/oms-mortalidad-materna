# Dashboard ("Python-Dash"): Python 3.12 slim con Dash, servido con gunicorn.
# La huella (sha256) fija la imagen exacta con la que se probó.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

WORKDIR /app

# Primero las librerías: si solo cambia el código, Docker reutiliza esta parte.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY assets ./assets

# Corre con un usuario sin privilegios.
RUN useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin dash
USER dash

EXPOSE 8050
# Escucha en todas las interfaces del contenedor; compose solo la publica en 127.0.0.1 de tu computadora.
CMD ["gunicorn", "--bind", "0.0.0.0:8050", "--workers", "2", "--timeout", "60", "app:server"]
