from bot import archivio_radar as a


def _ev(ricerca, semaforo, venduto_s=None, stato="attivo", incompleto="no", ts=1000.0):
    return {"ts": ts, "item_id": "1", "ricerca": ricerca, "semaforo": semaforo, "venduto_s": venduto_s,
            "stato": stato, "incompleto": incompleto, "storia": [[60, stato]]}


def test_riepilogo_conta_validi_e_venduti():
    ev = [_ev("A", "giallo", 300, "venduto"), _ev("A", "rosso"), _ev("A", "verde", 7200, "venduto"),
          _ev("A", "rosso", incompleto="si"), _ev("B", "rosso")]
    r = a.riepilogo_per_ricerca(ev)
    assert r["A"] == {"n": 4, "validi": 3, "venduti_1h": 1, "gialli_verdi": 2, "gialli_verdi_venduti": 1}
    assert r["B"]["n"] == 1


def test_riepilogo_rispetta_la_finestra():
    righe = a.righe_riepilogo([_ev("A", "rosso", ts=10.0)], giorni=1, adesso=10 + 2 * 86400)
    assert righe == []


def test_csv_ha_intestazione_e_righe():
    t = a.righe_csv([_ev("A", "rosso")]).splitlines()
    assert t[0].startswith("ts,item_id,ricerca")
    assert len(t) == 2


def test_report_giornaliero_candidati_e_motivi():
    from bot import archivio_radar as a
    t = 1000000.0
    v2 = [{"ts": t - 10, "ricerca": "A", "semaforo": "rosso", "motivo": "margine_basso"} for _ in range(12)]
    v2 += [{"ts": t - 10, "ricerca": "B", "semaforo": "giallo", "motivo": "ok"}, {"ts": t - 10, "ricerca": "B", "semaforo": "rosso", "motivo": "parola_vietata:x"},
           {"ts": t - 99999, "ricerca": "C", "semaforo": "rosso", "motivo": "x"}]
    righe, cand = a.report_giornaliero(v2, [], ore=24, adesso=t)
    assert cand == ["A"]
    assert any(r.startswith("A: 12 verdetti") and "margine_basso (12)" in r for r in righe)
    assert not any(r.startswith("C") for r in righe)
    assert "Candidate alla potatura" in a.testo_report(righe, cand)
