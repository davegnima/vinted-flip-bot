from bot.qualita_comps import fascia_numero, guasto_nella_descrizione, product_identity, punteggio_comparabili


def test_fasce():
    assert [fascia_numero(n) for n in (0, 2, 3, 4, 5, 7, 8, 14, 15)] == ["insufficiente", "insufficiente", "bassa", "bassa", "media", "media", "buona", "buona", "alta"]


def test_punteggio_buono_e_scarso():
    buoni = [(f"switch oled {i}", 100 + i) for i in range(15)]
    scarso = [("switch", 50), ("switch", 50), ("switch", 200)]
    assert punteggio_comparabili(buoni, 15, 15)["punteggio"] > 90
    assert punteggio_comparabili(scarso)["punteggio"] < 40
    assert punteggio_comparabili(scarso)["duplicati"] == 1
    assert punteggio_comparabili([])["punteggio"] == 0


def test_dichiara_cio_che_non_pesa():
    assert "venditori_distinti" in punteggio_comparabili([("a", 10)])["non_valutati"]


def test_identita_e_guasto():
    assert product_identity("Sony WH-CH520 nere", "Sony", 3678)["codice_modello"] == "wh-ch520"
    assert product_identity("Nintendo Switch", "Nintendo")["codice_modello"] is None
    assert guasto_nella_descrizione("Venduta per ricambi, non funziona") == "non funziona"
    assert guasto_nella_descrizione("Come nuova, funziona benissimo") is None


def test_stima_paese_jev(monkeypatch):
    from bot import jev
    monkeypatch.setattr(jev, "JEV_GIUDICE", True)
    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    risp = {"answers": {"paese": {"choice": "francia", "confidence": 0.9}}}
    monkeypatch.setattr(jev, "_chiama_jev", lambda corpo: risp)
    assert jev.stima_paese("Appareil photo", "Vendu avec boite") == ("francia", 0.9)
    risp["answers"]["paese"] = {"choice": "francia", "confidence": 0.3}
    assert jev.stima_paese("Appareil photo") is None
    risp["answers"]["paese"] = {"choice": "non_chiaro", "confidence": 0.95}
    assert jev.stima_paese("Camera") is None
