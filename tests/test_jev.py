"""Jev: tre domande chiuse, esito deciso dal codice (verdetto_jev). La rete e' finta."""
import io
import json

from bot import jev


def _r(tipo="oggetto_principale", completo="si", prezzo="sotto", conf=0.9):
    return {"tipo": (tipo, conf), "completo": (completo, conf), "prezzo": (prezzo, conf)}


def test_oggetto_principale_completo_sotto_stima_e_affare():
    assert jev.verdetto_jev(_r()) == ("affare_vero", 0.9)


def test_completo_non_dichiarato_resta_affare():
    assert jev.verdetto_jev(_r(completo="non_dichiarato"))[0] == "affare_vero"


def test_ricambio_lotto_o_replica_sono_falso_o_ricambio_anche_con_prezzo_basso():
    for tipo in ("ricambio_accessorio", "lotto", "replica_o_dubbio"):
        assert jev.verdetto_jev(_r(tipo=tipo))[0] == "falso_o_ricambio"


def test_incompleto_o_sopra_stima_e_non_affare():
    assert jev.verdetto_jev(_r(completo="no"))[0] == "non_affare"
    assert jev.verdetto_jev(_r(prezzo="sopra"))[0] == "non_affare"
    assert jev.verdetto_jev(_r(prezzo="in_linea"))[0] == "non_affare"


def test_confidenza_e_la_piu_bassa_delle_tre():
    risposte = {"tipo": ("oggetto_principale", 0.9), "completo": ("si", 0.4), "prezzo": ("sotto", 0.8)}
    assert jev.verdetto_jev(risposte) == ("affare_vero", 0.4)


def test_risposta_mancante_non_da_esito():
    assert jev.verdetto_jev({"tipo": ("oggetto_principale", 0.9)}) == (None, None)
    assert jev.verdetto_jev({**_r(), "prezzo": (None, None)}) == (None, None)


def test_giudica_manda_tre_domande_e_decide_il_codice(monkeypatch):
    monkeypatch.setattr(jev, "JEV_GIUDICE", True)
    monkeypatch.setenv("TYPESAFE_API_KEY", "chiave-finta")
    inviato = {}
    risposta = {"answers": {
        "tipo": {"choice": "oggetto_principale", "confidence": 0.8},
        "completo": {"choice": "si", "confidence": 0.7},
        "prezzo": {"choice": "sotto", "confidence": 0.9}}}

    def finto_urlopen(req, timeout):
        inviato.update(json.loads(req.data.decode()))
        return io.BytesIO(json.dumps(risposta).encode())

    monkeypatch.setattr(jev.urllib.request, "urlopen", finto_urlopen)
    assert jev.giudica("Psp portatile", 30, [60, 70], 80) == ("affare_vero", 0.7)
    assert set(inviato["questions"]) == {"tipo", "completo", "prezzo"}
    assert all(q["type"] == "choice" for q in inviato["questions"].values())


def test_giudica_senza_rete_non_blocca(monkeypatch):
    monkeypatch.setattr(jev, "JEV_GIUDICE", True)
    monkeypatch.setenv("TYPESAFE_API_KEY", "chiave-finta")

    def guasto(req, timeout):
        raise OSError("rete giu'")

    monkeypatch.setattr(jev.urllib.request, "urlopen", guasto)
    assert jev.giudica("x", 10, [20], 30) == (None, None)
