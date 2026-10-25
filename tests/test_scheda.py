

def test_avviso_solo_semaforo_verde_senza_cervello():
    from bot.scheda import avviso_solo_semaforo, testo_avviso_solo_semaforo, RIGA_SOLO_SEMAFORO
    info = {"title": "Borsa Prada", "brand": "Prada", "price": 20,
            "fair_value": {"semaforo": "🟢", "margine": 90.0, "fv": 110, "minimo": 90, "massimo": 130, "roi": 450, "conf": "media"}}
    assert avviso_solo_semaforo(info)
    testo = testo_avviso_solo_semaforo(info, "https://www.vinted.it/items/1-x")
    assert testo.startswith("🟢 ~+90 €") and RIGA_SOLO_SEMAFORO in testo and "vinted.it/items/1" in testo
    assert not avviso_solo_semaforo({"fair_value": {"semaforo": "🟡"}})
    assert not avviso_solo_semaforo({"fair_value": None})
