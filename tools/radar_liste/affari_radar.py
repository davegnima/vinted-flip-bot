# Percentuale di affare per ricerca del radar non moda (31/10): unisce le righe `RADAR V2 OMBRA` (semaforo, ricerca) e
# `TRACCIATO_RADAR` (esito di vendita) di un file di log. Affare = semaforo verde e venduto entro 1 h.
# Uso: python3 affari_radar.py LOG.txt        (il file si scarica con i filtri stretti di docs/procedure/analisi-log.md)
import re
import sys
from collections import defaultdict

RE_OMBRA = re.compile(r"RADAR V2 OMBRA \| item=(\d+) \| semaforo=(\w+) \| ok=(\w+) \| motivo=(\w+)(?:.*?\| ricerca=([^|\n]+?)\s*(?:\||$))?")
RE_TRACC = re.compile(r"TRACCIATO_RADAR \| item=(\d+).*?\| venduto_s=([\d-]+)")
MIN_CASI = 15
ENTRO_S = 3600


def leggi(righe):
    """({item: (semaforo, ricerca)}, {item: venduto_s o None}) dalle righe di log. Pura."""
    ombra, venduti = {}, {}
    for r in righe:
        m = RE_OMBRA.search(r)
        if m:
            ombra[m.group(1)] = (m.group(2), (m.group(5) or "-").strip())
            continue
        m = RE_TRACC.search(r)
        if m:
            venduti[m.group(1)] = int(m.group(2)) if m.group(2).isdigit() else None
    return ombra, venduti


def tabella(ombra, venduti):
    """{ricerca: {semaforo: [n, n_con_esito, n_veloci]}}. Con esito = riga TRACCIATO_RADAR presente. Pura."""
    t = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for item, (sem, ricerca) in ombra.items():
        c = t[ricerca][sem]
        c[0] += 1
        if item in venduti:
            c[1] += 1
            if venduti[item] is not None and venduti[item] <= ENTRO_S:
                c[2] += 1
    return t


ENTRO_ROSSI_S = 300
RE_TITOLO = re.compile(r"\| titolo=(.*)$")


def rossi_veloci(righe, entro_s=ENTRO_ROSSI_S):
    """[(item, ricerca, motivo, venduto_s, titolo)] dei rossi spariti entro `entro_s` secondi: i verdetti da rivedere (31/10). Pura."""
    rossi, venduti = {}, {}
    for r in righe:
        m = RE_OMBRA.search(r)
        if m:
            if m.group(2) == "rosso":
                t = RE_TITOLO.search(r)
                rossi[m.group(1)] = ((m.group(5) or "-").strip(), m.group(4), (t.group(1).strip() if t else ""))
            continue
        m = RE_TRACC.search(r)
        if m and m.group(2).isdigit():
            venduti[m.group(1)] = int(m.group(2))
    return [(i, rossi[i][0], rossi[i][1], venduti[i], rossi[i][2]) for i in rossi if i in venduti and venduti[i] <= entro_s]


def stampa(t):
    print(f"ricerca | semaforo | annunci | con esito | venduti entro 1 h | percentuale (solo con >= {MIN_CASI} casi con esito)")
    for ricerca in sorted(t):
        for sem in ("verde", "giallo", "rosso"):
            if sem in t[ricerca]:
                n, esito, veloci = t[ricerca][sem]
                pct = f"{100 * veloci / esito:.0f}%" if esito >= MIN_CASI else "pochi dati"
                print(f"{ricerca} | {sem} | {n} | {esito} | {veloci} | {pct}")


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        righe = f.readlines()
    stampa(tabella(*leggi(righe)))
    rv = rossi_veloci(righe)
    print(f"\nRossi spariti entro {ENTRO_ROSSI_S // 60} minuti (verdetti da rivedere): {len(rv)}")
    for item, ricerca, motivo, vend, titolo in rv:
        print(f"{item} | {ricerca} | {motivo} | venduto dopo {vend} s | {titolo}")
