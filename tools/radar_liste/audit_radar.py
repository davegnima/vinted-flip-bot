# Audit dei falsi negativi del radar non moda (01/11, tappa 4): legge le righe `TRACCIATO_RADAR` di un file di log e, per ogni
# motivo di scarto (rossi), conta quanti annunci tracciati sono spariti entro 1 h e quanti avevano margine >= 50 e ROI >= 100
# secondo il calcolo (possibili affari persi). Solo misura: "sparito" resta ambiguo (venduto o cancellato), quindi e' un limite alto.
# Uso: python3 audit_radar.py LOG.txt
import re
import sys
from collections import defaultdict

RE_RIGA = re.compile(r"TRACCIATO_RADAR \|(.*)$")
MIN_CASI = 15
ENTRO_S = 3600
MARGINE_MIN, ROI_MIN = 50.0, 100.0


def _campi(riga):
    m = RE_RIGA.search(riga)
    if not m:
        return None
    return {k.strip(): v.strip() for k, _, v in (p.partition("=") for p in m.group(1).split(" | ")) if k.strip()}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def tabella(righe):
    """{motivo: [n, con_esito, veloci, persi]} per i soli rossi. con_esito = serie chiusa con venduto_s o stato noto;
    veloci = sparito entro 1 h; persi = veloci con margine >= 50 e ROI >= 100 nel calcolo. Pura."""
    t = defaultdict(lambda: [0, 0, 0, 0])
    for r in righe:
        c = _campi(r)
        if not c or c.get("semaforo") != "rosso":
            continue
        motivo = (c.get("motivo") or "-").split(":")[0]
        riga = t[motivo]
        riga[0] += 1
        vend = c.get("venduto_s", "-")
        if c.get("incompleto") == "si":
            continue
        riga[1] += 1
        if vend.isdigit() and int(vend) <= ENTRO_S:
            riga[2] += 1
            m, roi = _num(c.get("margine")), _num(c.get("roi"))
            if m is not None and roi is not None and m >= MARGINE_MIN and roi >= ROI_MIN:
                riga[3] += 1
    return t


def stampa(t):
    print(f"motivo | scartati tracciati | con esito | spariti entro 1 h | quota | possibili affari persi (solo con >= {MIN_CASI} casi con esito la quota e' valida)")
    for motivo in sorted(t, key=lambda k: -t[k][0]):
        n, esito, veloci, persi = t[motivo]
        quota = f"{100 * veloci / esito:.0f}%" if esito >= MIN_CASI else "pochi dati"
        print(f"{motivo} | {n} | {esito} | {veloci} | {quota} | {persi}")


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        stampa(tabella(f.readlines()))
