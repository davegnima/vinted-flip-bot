# Calibrazione della stima di rivendita (01/11, tappa 5, livello 3): legge le righe `OPERAZIONE` (comando /rivenduto) di un
# file di log e confronta la stima del bot (`stima_bot`) con il prezzo di rivendita reale. Il coefficiente per la tappa 2
# (`bot.valore_mercato.coefficiente_vendita`) esce solo con >= 15 casi; sotto, resta "non calibrato". Uso: python3 calibrazione.py LOG.txt
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from bot.valore_mercato import coefficiente_vendita  # noqa: E402

RE_OP = re.compile(r"OPERAZIONE \|(.*)$")


def casi(righe):
    """[(stima_bot, prezzo_reale)] dalle rivendite con stima del bot > 0. Pura."""
    out = []
    for r in righe:
        m = RE_OP.search(r)
        if not m:
            continue
        c = {k.strip(): v.strip() for k, _, v in (p.partition("=") for p in m.group(1).split(" | ")) if k.strip()}
        try:
            if c.get("tipo") == "rivendita" and float(c["stima_bot"]) > 0:
                out.append((float(c["stima_bot"]), float(c["prezzo"])))
        except (KeyError, ValueError):
            continue
    return out


def riepilogo(coppie):
    rapporti = [reale / stima for stima, reale in coppie]
    coeff, stato = coefficiente_vendita(rapporti)
    mediana = round(statistics.median(rapporti), 2) if rapporti else None
    return {"casi": len(rapporti), "mediana_reale_su_stima": mediana, "coefficiente": coeff, "stato": stato}


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        print(riepilogo(casi(f.readlines())))
