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
    righe, cand, vel = a.report_giornaliero(v2, [], ore=24, adesso=t)
    assert cand == ["A"]
    assert righe[0]["nome"] == "A" and righe[0]["tot"] == 12 and righe[0]["motivo"] == "margine_basso"
    assert not any(r["nome"] == "C" for r in righe)
    tr = [{"ts": t - 5, "semaforo": "giallo", "stato": "venduto", "venduto_s": 300, "storia": [1], "incompleto": "no"},
          {"ts": t - 5, "semaforo": "giallo", "stato": "attivo", "storia": [1], "incompleto": "no"}]
    v = a.velocita_per_semaforo(tr, t - 100)
    assert v["giallo"] == {"validi": 2, "venduti": 1, "mediana_s": 300}
    txt = a.testo_report(righe, cand, v)
    assert "```" in txt and "giallo: 1/2 venduti (50%), mediana 5m" in txt and "Da potare" in txt


# --- esito finale dei gialli e verdi (radar_esito) ---
import asyncio
import pytest
from bot import radar

_OK_G = {"verdetto": "conferma", "confidenza": 0.9, "rivendita_eur": 120.0, "rivendita_confidenza": 0.8, "motivo": "ok"}
_P = {"title": "Switch oled", "price": "40", "query_name": "V2 switch", "brand": "Nintendo"}
_U = "https://www.vinted.it/items/801-switch"
_V2_OK = {"semaforo": "giallo", "jev": "affare_vero", "jev_conf": 0.95, "rivendita": 150.0, "brand": "Nintendo"}


def _invia(monkeypatch, v2, g=_OK_G, jev_richiesto=True, invio=True, rivaluta=None, ricerca_modello=False, prima=None):
    eventi = []

    async def finto_invia(testo, foto, suono=False, ricerca=None, url=None):
        if invio == "errore":
            raise RuntimeError("boom")
        return invio

    async def finta_controlla(*a, **k):
        return g

    monkeypatch.setattr(radar, "RADAR_JEV_RICHIESTO", jev_richiesto)
    monkeypatch.setattr(radar, "RADAR_SEMAFORI", {"verde", "giallo"})
    monkeypatch.setattr(radar, "RADAR_VERIFICA", True)
    monkeypatch.setattr(radar, "RADAR_VERIFICA_SCARTA", True)
    monkeypatch.setattr(radar, "_invia_radar", finto_invia)
    monkeypatch.setattr(radar, "radar_in_pausa", lambda *a, **k: bool(prima == "pausa"))
    monkeypatch.setattr(radar, "controlla_gemini", finta_controlla)
    monkeypatch.setattr(radar.db, "scrivi_evento", lambda tipo, item_id=None, brand=None, dati=None, ts=None: eventi.append((tipo, item_id, dati)))
    radar._radar_inviati.clear()
    esito = {}
    asyncio.run(radar.invia_verdetto_v2(_P, _U, v2, rivaluta=rivaluta, esito=esito))
    return [e for e in eventi if e[0] == "radar_esito"]


@pytest.mark.parametrize("nome,v2,kw,atteso", [
    ("inviato", _V2_OK, {}, "inviato"),
    ("jev", {**_V2_OK, "jev": "prezzo_normale"}, {}, "scartato_jev"),
    ("jev_conf", {**_V2_OK, "jev_conf": 0.1}, {}, "jev_conf_bassa"),
    ("gemini", _V2_OK, {"g": {**_OK_G, "verdetto": "scarta", "motivo": "rotto"}}, "scartato_gemini"),
    ("gemini_stima", _V2_OK, {"g": {**_OK_G, "rivendita_eur": 20.0}}, "scartato_gemini"),
    ("verifica", {**_V2_OK, "verificata": {"semaforo": "rosso", "n_stesso": 1, "n_giudicati": 9}}, {}, "scartato_verifica"),
    ("invio", _V2_OK, {"invio": False}, "errore_invio"),
    ("eccezione", _V2_OK, {"invio": "errore"}, "errore_invio"),
    ("pausa", _V2_OK, {"prima": "pausa"}, "altro"),
])
def test_un_evento_per_ramo(monkeypatch, nome, v2, kw, atteso):
    ev = _invia(monkeypatch, v2, **kw)
    assert len(ev) == 1
    d = ev[0][2]
    assert d["esito"] == atteso and ev[0][1] == "801"
    assert d["ricerca"] == "V2 switch" and d["semaforo"] == "giallo" and d["titolo"] == "Switch oled" and "modello" in d
    assert (d["motivo"] is not None) == (atteso != "inviato")


def test_ramo_rivalutazione(monkeypatch):
    async def riv(parsed, url, v2, g):
        return {**v2, "jev": "prezzo_normale"}
    ev = _invia(monkeypatch, _V2_OK, g={**_OK_G, "ricerca_modello": "switch lite"}, rivaluta=riv)
    assert ev[0][2]["esito"] == "scartato_rivalutazione" and "gemini" in ev[0][2]


def test_rosso_non_scrive_evento(monkeypatch):
    assert _invia(monkeypatch, {"semaforo": "rosso", "motivo": "margine_basso"}) == []


def test_somma_esiti_uguale_a_gialli_piu_verdi(monkeypatch):
    t = 1000000.0
    casi = [_V2_OK, {**_V2_OK, "semaforo": "verde"}, {**_V2_OK, "jev": "prezzo_normale"}, {**_V2_OK, "jev_conf": 0.1}]
    esiti = []
    for v2 in casi:
        esiti += [{"ts": t - 5, **e[2]} for e in _invia(monkeypatch, v2)]
    v2ev = [{"ts": t - 5, "ricerca": "V2 switch", "semaforo": c["semaforo"]} for c in casi] + [{"ts": t - 5, "ricerca": "V2 switch", "semaforo": "rosso", "motivo": "x"}]
    righe, _c, _v = a.report_giornaliero(v2ev, [], ore=24, adesso=t, eventi_esito=esiti)
    gv, inv, scr, senza = a.funnel(righe, esiti, 24, adesso=t)
    assert (gv, inv, scr, senza) == (4, 2, 2, 0)
    assert righe[0]["inviati"] == 2 and righe[0]["scartati"] == 2
    assert "inv" in a.testo_report(righe, [], {})
    # un giallo senza evento si vede
    assert a.funnel(righe, esiti[:-1], 24, adesso=t)[3] == 1


def test_colonne_e_tracciato_hanno_i_campi_nuovi():
    for c in ("modello", "titolo", "gemini", "esito_finale"):
        assert c in a.COLONNE
    from bot import tracciamento as tr
    riga = tr._riga_tracciato("1", "x", 10, [(60, "attivo")], {"modello": "switch", "titolo": "t", "gemini": "conferma riv=120", "esito_finale": "inviato"}, prefisso="TRACCIATO_RADAR")
    assert "modello=switch" in riga and "gemini=conferma riv=120" in riga and "esito_finale=inviato" in riga
