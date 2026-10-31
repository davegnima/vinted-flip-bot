import importlib.util
import os

_p = os.path.join(os.path.dirname(__file__), "..", "tools", "radar_liste", "affari_radar.py")
_s = importlib.util.spec_from_file_location("affari_radar", _p)
ar = importlib.util.module_from_spec(_s)
_s.loader.exec_module(ar)

RIGHE = [
    "x | RADAR V2 OMBRA | item=1 | semaforo=verde | ok=True | motivo=ok | prezzo=40 | n=13 | q=nintendo switch | ricerca=V2 switch | titolo=a",
    "x | RADAR V2 OMBRA | item=2 | semaforo=rosso | ok=False | motivo=sopra_riferimento | prezzo=300 | limite=148 | n=8 | ricerca=V2 ps5",
    "x | TRACCIATO_RADAR | item=1 | brand='n/d' | stato=sparito | venduto_s=600 | controlli=3",
    "x | TRACCIATO_RADAR | item=2 | brand='n/d' | venduto_s=-",
]


def test_leggi_e_tabella():
    ombra, venduti = ar.leggi(RIGHE)
    assert ombra["1"] == ("verde", "V2 switch") and ombra["2"][1] == "V2 ps5"
    assert venduti == {"1": 600, "2": None}
    t = ar.tabella(ombra, venduti)
    assert t["V2 switch"]["verde"] == [1, 1, 1] and t["V2 ps5"]["rosso"] == [1, 1, 0]
