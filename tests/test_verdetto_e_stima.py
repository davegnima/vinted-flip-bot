import main_telethon as m


def test_consolida_target():
    c = m.consolida_target_cervello
    assert c([160]) == (160.0, 1.0, False)
    valore, spread, instabile = c([52, 160, 60])
    assert valore == 60 and instabile
    assert c([100, 110])[0] == 105 and not c([100, 110])[2]
    assert c([52, 160])[0] == 52  # con 2 campioni divergenti si tiene il piu' basso
    assert c([]) == (None, None, False)


def _v(target, **extra):
    v = {
        "prezzo_target_vendita_eur": target, "comp_riferimento_eur": target, "legit_verdetto": "probabilmente_autentico",
        "corrispondenza_brand": "corrisponde", "domanda_mercato": "media", "segnali_domanda": [],
        "materiale_confermato": True, "difetto_strutturale": False, "sconto_difetto_pct": 0,
        "sconto_ask_applicato_pct": 0, "fascia_taglia": "centrale",
    }
    v.update(extra)
    return v


def test_verdetto_deterministico_e_monotono_nel_target():
    # Stesso capo, stesso prezzo: piu' alto il target, mai un esito peggiore.
    ordine = {"NON COMPRARE": 0, "CHIEDI ALTRE FOTO": 1, "TRATTA": 2, "COMPRA": 3}
    esiti = []
    for target in (20, 60, 120, 250):
        r = m.calcola_verdetto(m.valida_payload_cervello(_v(target))[0], 20.0)
        assert r == m.calcola_verdetto(m.valida_payload_cervello(_v(target))[0], 20.0)  # puro
        esiti.append(ordine[r["decisione"]])
    assert esiti == sorted(esiti)
    assert esiti[0] == 0  # target 20 con acquisto 20: nessun margine


def test_margine_e_roi_coerenti():
    r = m.calcola_verdetto(m.valida_payload_cervello(_v(120))[0], 20.0)
    assert r["margine"] is not None and r["roi"] is not None and r["margine"] > 0
