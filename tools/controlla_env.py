"""Confronta le variabili d'ambiente lette dal codice con `.env.example`.

Uso: python3 tools/controlla_env.py [--default]
Stampa quante variabili mancano in `.env.example` e quante sono morte
(documentate ma non piu' lette). Con --default elenca anche il default letto
dal codice (solo letterali; altrimenti "?").
Esce con codice 1 se c'e' almeno una mancante o una morta.
"""
import ast
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
FILE_ENV = RADICE / ".env.example"


def _file_codice():
    yield RADICE / "main_telethon.py"
    yield from sorted((RADICE / "bot").rglob("*.py"))


def _nome_attr(nodo):
    """'os.environ.get' ecc. come stringa, altrimenti ''."""
    parti = []
    while isinstance(nodo, ast.Attribute):
        parti.append(nodo.attr)
        nodo = nodo.value
    if isinstance(nodo, ast.Name):
        parti.append(nodo.id)
    return ".".join(reversed(parti))


def _testo_default(nodo):
    if nodo is None:
        return ""
    try:
        valore = ast.literal_eval(nodo)
    except Exception:
        return "?"
    return "" if valore is None else str(valore)


def variabili_lette():
    """Dict nome -> default (stringa) letto dal codice."""
    trovate = {}
    for percorso in _file_codice():
        if not percorso.exists():
            continue
        albero = ast.parse(percorso.read_text(encoding="utf-8"))
        for nodo in ast.walk(albero):
            nome = default = None
            if isinstance(nodo, ast.Call) and nodo.args:
                if _nome_attr(nodo.func) in ("os.environ.get", "os.getenv", "_env_float"):
                    primo = nodo.args[0]
                    if isinstance(primo, ast.Constant) and isinstance(primo.value, str):
                        nome = primo.value
                        default = _testo_default(nodo.args[1]) if len(nodo.args) > 1 else ""
            elif isinstance(nodo, ast.Subscript) and _nome_attr(nodo.value) == "os.environ":
                indice = nodo.slice
                if isinstance(indice, ast.Constant) and isinstance(indice.value, str):
                    nome, default = indice.value, ""
            if nome and (nome not in trovate or trovate[nome] in ("", "?")):
                trovate[nome] = default
    return trovate


def variabili_documentate():
    """Nomi dichiarati in `.env.example` (righe NOME=...), anche commentate con '#NOME='."""
    nomi = []
    for riga in FILE_ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*#?\s*([A-Z][A-Z0-9_]*)=", riga)
        if m:
            nomi.append(m.group(1))
    return nomi


def confronta():
    lette = variabili_lette()
    doc = set(variabili_documentate())
    mancanti = sorted(set(lette) - doc)
    morte = sorted(doc - set(lette))
    return lette, mancanti, morte


def main():
    lette, mancanti, morte = confronta()
    print(f"lette={len(lette)} documentate={len(set(variabili_documentate()))}")
    if "--default" in sys.argv:
        for nome in sorted(lette):
            print(f"{nome}={lette[nome]}")
    print(f"mancanti: {len(mancanti)}")
    for nome in mancanti:
        print(f"  {nome}")
    print(f"morte: {len(morte)}")
    for nome in morte:
        print(f"  {nome}")
    return 1 if (mancanti or morte) else 0


if __name__ == "__main__":
    sys.exit(main())
