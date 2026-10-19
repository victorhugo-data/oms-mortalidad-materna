"""Señal de vida del recolector. La usa el healthcheck de compose.yaml.

El recolector toca ARCHIVO_LATIDO por lo menos cada minuto. Si la señal tiene menos
de 5 minutos, el contenedor está sano. El healthcheck corre: python salud.py
"""
import sys
import time
from pathlib import Path

ARCHIVO_LATIDO = Path("/tmp/recolector_vivo")
MAXIMO_SEGUNDOS = 5 * 60


def latido():
    """Deja la señal de que el recolector sigue vivo."""
    ARCHIVO_LATIDO.touch()


def esperar(segundos):
    """Espera sin dejar de dar señales de vida."""
    fin = time.monotonic() + segundos
    while True:
        latido()
        falta = fin - time.monotonic()
        if falta <= 0:
            return
        time.sleep(min(falta, 60))


def esta_sano():
    try:
        edad = time.time() - ARCHIVO_LATIDO.stat().st_mtime
    except FileNotFoundError:
        return False
    return edad < MAXIMO_SEGUNDOS


if __name__ == "__main__":
    sys.exit(0 if esta_sano() else 1)
