import importlib.util
import pathlib

from bot.operazioni import margine_reale, parse_operazione


def test_parse_operazione():
    assert parse_operazione("/comprato https://www.vinted.it/items/1234567890-switch 40 5") == {"tipo": "acquisto", "item": "1234567890", "prezzo": 40.0, "extra": 5.0}
    assert parse_operazione("/rivenduto 1234567890 95,5 3")["prezzo"] == 95.5
    assert parse_operazione("/comprato 1234567890 abc") is None
    assert parse_operazione("/comprato 12 40") is None
    assert parse_operazione("/altro 1234567890 40") is None


def test_margine_reale():
    assert margine_reale(40, 8, 120) == (72.0, 150.0)
    assert margine_reale(0, 0, 10) == (10.0, None)


def test_calibrazione_sotto_soglia():
    sp = importlib.util.spec_from_file_location("calibrazione", pathlib.Path(__file__).parent.parent / "tools/radar_liste/calibrazione.py")
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    righe = ["x OPERAZIONE | tipo=rivendita | item=1 | prezzo=80.0 | stima_bot=100.0", "x OPERAZIONE | tipo=acquisto | item=1 | prezzo=40.0"]
    r = mod.riepilogo(mod.casi(righe))
    assert r["casi"] == 1 and r["stato"] == "non_calibrato" and r["coefficiente"] == 1.0
