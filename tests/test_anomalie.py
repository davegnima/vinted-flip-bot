"""Tool anomalie.py (01/11): parsing delle righe di log, anomalie, tabelle."""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parent.parent / "tools" / "radar_liste" / "anomalie.py"
_s = importlib.util.spec_from_file_location("anomalie", _p)
an = importlib.util.module_from_spec(_s)
_s.loader.exec_module(an)

RIGHE = [
    "2026-11-01 10:00:00,1 | INFO | RADAR V2 OMBRA | item=1 | semaforo=verde | ok=True | motivo=ok | prezzo=35.0 | rivendita=190.0 | margine=131.0 | roi=328.0 | n=14 | ricerca=Fotocamere digitali | titolo=Sony h1",
    "2026-11-01 10:00:01,1 | INFO | TRACCIATO_RADAR | item=1 | brand='Sony' | prezzo=35.0 | semaforo=verde | venduto_s=300 | ricerca=Fotocamere digitali",
    "2026-11-01 10:01:00,1 | INFO | RADAR V2 OMBRA | item=2 | semaforo=rosso | ok=False | motivo=margine_basso | prezzo=20.0 | rivendita=30.0 | margine=2.0 | roi=5.0 | n=9 | ricerca=Console | titolo=Wii | usato",
    "2026-11-01 10:01:01,1 | INFO | TRACCIATO_RADAR | item=2 | brand='Nintendo' | prezzo=20.0 | venduto_s=- | ricerca=Console",
]


def test_leggi_e_anomalie():
    dati = an.marca_anomalie(an.leggi(RIGHE))
    assert set(dati) == {"1", "2"}
    assert dati["1"]["anomalia"] and dati["1"]["brand"] == "sony" and dati["1"]["venduto_s"] == 300
    assert not dati["2"]["anomalia"] and dati["2"]["venduto_s"] is None
    assert dati["2"]["titolo"] == "Wii | usato"  # il titolo puo' contenere barre


def test_tabella_conta_veloci():
    dati = an.marca_anomalie(an.leggi(RIGHE))
    t = an.tabella(dati, lambda d: d["ricerca"])
    assert t[0] == ("Fotocamere digitali", 1, 1, 1, 1)
