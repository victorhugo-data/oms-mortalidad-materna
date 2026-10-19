# Recolector ("API-Ubuntu"): Ubuntu 24.04 con Python 3.12.
# La huella (sha256) fija la imagen exacta con la que se probó.
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

# Python y los certificados para hablar con la API por HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Primero las librerías: si solo cambia el código, Docker reutiliza esta parte.
COPY requirements.txt .
RUN python3 -m venv /app/venv \
 && /app/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Corre con un usuario sin privilegios.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin recolector
USER recolector

ENTRYPOINT ["/app/venv/bin/python", "/app/recolector.py"]
