

def test_avviso_solo_semaforo_verde_senza_cervello():
    from bot.scheda import avviso_solo_semaforo, testo_avviso_solo_semaforo, RIGA_SOLO_SEMAFORO
    info = {"title": "Borsa Prada", "brand": "Prada", "price": 20,
            "fair_value": {"semaforo": "🟢", "margine": 90.0, "fv": 110, "minimo": 90, "massimo": 130, "roi": 450, "conf": "media"}}
    assert avviso_solo_semaforo(info)
    testo = testo_avviso_solo_semaforo(info, "https://www.vinted.it/items/1-x")
    assert testo.startswith("🟢 ~+90 €") and RIGA_SOLO_SEMAFORO in testo and "vinted.it/items/1" in testo
    assert not avviso_solo_semaforo({"fair_value": {"semaforo": "🟡"}})
    assert not avviso_solo_semaforo({"fair_value": None})


def test_testo_solo_semaforo_scelto_usa_il_semaforo_vero(monkeypatch):
    # 1/11: SOLO_SEMAFORO=1 segnala anche i 🟡 della regola del preavviso e dice che l'autenticita' non e' verificata
    from bot import scheda
    monkeypatch.setattr(scheda, "SOLO_SEMAFORO", True)
    info = {"title": "Cappotto", "brand": "Max Mara", "price": 30, "fair_value": {"semaforo": "🟡", "margine": 55.0, "fv": 85, "minimo": 70, "massimo": 100, "roi": 180, "conf": "media"}}
    testo = scheda.testo_avviso_solo_semaforo(info, "https://www.vinted.it/items/2-x")
    assert testo.startswith("🟡 ~+55 €") and scheda.RIGA_SOLO_SEMAFORO_SCELTO in testo
    assert "Solo semaforo" in scheda._stato_analisi_testo(3)
