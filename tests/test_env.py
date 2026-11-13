"""`.env.example` deve elencare esattamente le variabili d'ambiente lette dal codice."""
import importlib.util
from pathlib import Path

_PERCORSO = Path(__file__).resolve().parent.parent / "tools" / "controlla_env.py"
_spec = importlib.util.spec_from_file_location("controlla_env", _PERCORSO)
controlla_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(controlla_env)


def test_variabili_lette_sono_documentate():
    _, mancanti, _ = controlla_env.confronta()
    assert not mancanti, f"manca in .env.example: {mancanti}"


def test_variabili_documentate_sono_lette():
    _, _, morte = controlla_env.confronta()
    assert not morte, f"in .env.example ma non piu' lette dal codice: {morte}"
