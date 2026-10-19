import sys
from pathlib import Path

# Para que las pruebas puedan importar los módulos del recolector.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
