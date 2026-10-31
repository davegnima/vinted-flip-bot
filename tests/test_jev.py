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


JPEG = b"\xff\xd8\xff\xe0" + b"0" * 50
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50


def _finto(monkeypatch, risposte_per_chiamata):
    """urlopen finto: ogni chiamata riceve la successiva risposta (oppure un'eccezione) e registra la richiesta."""
    richieste = []

    def urlopen(req, timeout):
        richieste.append(json.loads(req.data.decode()))
        risultato = risposte_per_chiamata.pop(0)
        if isinstance(risultato, Exception):
            raise risultato
        return io.BytesIO(json.dumps(risultato).encode())

    monkeypatch.setattr(jev.urllib.request, "urlopen", urlopen)
    return richieste


def _risposta(foto=None, token=300):
    answers = {"tipo": {"choice": "oggetto_principale", "confidence": 0.8},
               "completo": {"choice": "si", "confidence": 0.7},
               "prezzo": {"choice": "sotto", "confidence": 0.9}}
    if foto:
        answers["foto"] = {"choice": foto, "confidence": 0.6}
    return {"answers": answers, "usage": {"input_tokens": token}}


def _attiva(monkeypatch, foto_on):
    monkeypatch.setattr(jev, "JEV_GIUDICE", True)
    monkeypatch.setattr(jev, "JEV_FOTO", foto_on)
    monkeypatch.setenv("TYPESAFE_API_KEY", "chiave-finta")


def test_formato_foto_riconosce_png_e_jpeg_e_scarta_il_resto():
    assert jev._formato_foto(PNG) == "png"
    assert jev._formato_foto(JPEG) == "jpeg"
    assert jev._formato_foto(b"GIF89a") is None
    assert jev._formato_foto(None) is None


def test_foto_non_corrisponde_e_falso_o_ricambio():
    assert jev.verdetto_jev({**_r(), "foto": ("non_corrisponde", 0.9)})[0] == "falso_o_ricambio"
    assert jev.verdetto_jev({**_r(), "foto": ("corrisponde", 0.9)})[0] == "affare_vero"
    assert jev.verdetto_jev({**_r(), "foto": ("non_chiaro", 0.9)})[0] == "affare_vero"


def test_con_foto_manda_immagine_intestazione_e_domanda(monkeypatch):
    _attiva(monkeypatch, foto_on=True)
    richieste = _finto(monkeypatch, [_risposta(foto="corrisponde")])
    esito = jev.giudica("Psp portatile", 30, [60, 70], 80, foto=JPEG)
    corpo = richieste[0]
    assert "foto1" in corpo["state"]
    assert corpo["assets"]["foto1"]["format"] == "jpeg" and corpo["assets"]["foto1"]["type"] == "image"
    assert "foto" in corpo["questions"] and set(corpo["questions"]) == {"tipo", "completo", "prezzo", "foto"}
    assert esito == ("affare_vero", 0.6)


def test_senza_flag_la_foto_non_parte(monkeypatch):
    _attiva(monkeypatch, foto_on=False)
    richieste = _finto(monkeypatch, [_risposta()])
    jev.giudica("Psp portatile", 30, [60], 80, foto=JPEG)
    assert "assets" not in richieste[0] and "foto" not in richieste[0]["questions"]


def test_richiesta_con_foto_rifiutata_riprova_solo_testo(monkeypatch):
    _attiva(monkeypatch, foto_on=True)
    richieste = _finto(monkeypatch, [RuntimeError("400 immagine non valida"), _risposta()])
    esito = jev.giudica("Psp portatile", 30, [60], 80, foto=JPEG)
    assert "assets" in richieste[0] and "assets" not in richieste[1]
    assert esito == ("affare_vero", 0.7)


def test_fascia_di_confidenza():
    assert jev.fascia(0.9) == "passa" and jev.fascia(0.85) == "passa"
    assert jev.fascia(0.75) == "da_rivedere" and jev.fascia(0.7) == "da_rivedere"
    assert jev.fascia(0.69) == "scartato" and jev.fascia(None) == "scartato"


def test_descrizione_e_titoli_simili_vanno_a_jev_e_simili_non_cambia_l_esito(monkeypatch):
    monkeypatch.setattr(jev, "JEV_GIUDICE", True)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    corpi = []

    def finto(corpo):
        corpi.append(corpo)
        risp = {k: {"choice": s, "confidence": 0.9} for k, s in
                (("tipo", "oggetto_principale"), ("completo", "si"), ("prezzo", "sotto"))}
        if "simili" in corpo["questions"]:
            risp["simili"] = {"choice": "diverso", "confidence": 0.8}
        return {"answers": risp}
    monkeypatch.setattr(jev, "_chiama_jev", finto)
    esito, conf, simili, motivo = jev.giudica_completo("Dyson V11", 40, [100, 120], 100, descrizione="  non   funziona " + "x" * 900,
                                               titoli_simili=["Dyson V11 Absolute", "Dyson V8"])
    assert (esito, conf, simili) == ("affare_vero", 0.9, ("diverso", 0.8))
    assert motivo == ("ok", jev.FRASI_MOTIVO["ok"] + ", ma i simili non sono lo stesso modello")
    stato = corpi[0]["state"]
    assert "Descrizione del venditore: non funziona" in stato and "- Dyson V8" in stato
    assert len(stato.split("Descrizione del venditore: ")[1].split("\n")[0]) <= jev.MAX_DESCRIZIONE
    # senza titoli dei simili la domanda non c'e' e il terzo valore e' None
    assert jev.giudica_completo("Dyson V11", 40, [100], 100)[2] is None
    assert "simili" not in corpi[1]["questions"]


def test_motivo_jev_un_codice_per_ogni_caso():
    assert jev.motivo_jev(_r())[0] == "ok"
    assert jev.motivo_jev(_r(tipo="ricambio_accessorio"))[0] == "ricambio"
    assert jev.motivo_jev(_r(tipo="lotto"))[0] == "lotto"
    assert jev.motivo_jev(_r(tipo="replica_o_dubbio"))[0] == "replica_dubbio"
    assert jev.motivo_jev(_r(completo="no"))[0] == "guasto_incompleto"
    assert jev.motivo_jev(_r(prezzo="sopra"))[0] == "prezzo_alto"
    assert jev.motivo_jev(_r(prezzo="in_linea"))[0] == "prezzo_in_linea"
    assert jev.motivo_jev({**_r(), "foto": ("non_corrisponde", 0.9)})[0] == "foto_diversa"
    assert jev.motivo_jev({"tipo": ("lotto", 0.9)}) == (None, None)


def test_motivo_jev_stesso_ordine_dell_esito():
    # ricambio + rotto: l'esito e' falso_o_ricambio, quindi il motivo e' il ricambio (non il guasto)
    r = _r(tipo="ricambio_accessorio", completo="no")
    assert jev.verdetto_jev(r)[0] == "falso_o_ricambio" and jev.motivo_jev(r)[0] == "ricambio"
    r = _r(completo="no", prezzo="sopra")
    assert jev.verdetto_jev(r)[0] == "non_affare" and jev.motivo_jev(r)[0] == "guasto_incompleto"


def test_descrizione_jev_in_italiano():
    f = jev.FRASI_MOTIVO["guasto_incompleto"]
    assert jev.descrizione_jev("non_affare", 0.9, f) == f"non e' un affare, {f} (confidenza 0.9)"
    assert jev.descrizione_jev("affare_vero", 0.8, None) == "affare (confidenza 0.8)"
