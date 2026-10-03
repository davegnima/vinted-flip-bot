"""Guardia della struttura a moduli: ogni modulo di bot/ deve potersi importare da solo in un interprete pulito
(niente import circolari, niente dipendenze nascoste da main_telethon) e i client HTTP ri-assegnati a runtime non
devono mai essere importati per nome (catturerebbero None)."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent
MODULI = sorted(p.stem for p in (RADICE / "bot").glob("*.py") if p.stem != "__init__")


@pytest.mark.parametrize("modulo", MODULI)
def test_modulo_importabile_da_solo(modulo):
    r = subprocess.run([sys.executable, "-c", f"import bot.{modulo}"], cwd=RADICE, env=os.environ.copy(),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]


def test_client_http_mai_importati_per_nome():
    vietati = r"(_client_generico|_client_telegram|_CLIENT_VINTED_AUTH_KEY|_CLIENT_VINTED_AUTH)\b"
    for p in [RADICE / "main_telethon.py", *(RADICE / "bot").glob("*.py")]:
        if p.name == "http_clients.py":
            continue
        for n, riga in enumerate(p.read_text().split("\n"), 1):
            if re.match(r"\s*from bot\.http_clients import", riga) and re.search(vietati, riga):
                pytest.fail(f"{p.name}:{n} importa un client per nome: {riga.strip()}")
