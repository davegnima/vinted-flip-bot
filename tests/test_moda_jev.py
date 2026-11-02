"""Verifica Jev dei brand nuovi della moda (bot/moda_jev.py): URL dei comparabili, decisione, righe del messaggio."""
import tests.conftest  # noqa: F401
from bot import moda_jev as mj


def test_url_comparabili_con_brand_categoria_e_testo():
    u = mj.url_comparabili("zimmermann", "abito lungo", 10)
    assert "brand_ids[]=172418" in u and "catalog[]=10" in u and "search_text=abito%20lungo" in u


def test_url_comparabili_senza_id_brand_e_none():
    assert mj.url_comparabili("marchio inesistente", "x", 1) is None


def test_decidi_conferma_se_i_comparabili_reggono_e_la_foto_e_ok():
    assert mj.decidi({"ok": True}, ("originale_plausibile", 0.9)) == ("conferma", "ok")


def test_decidi_scarta_se_il_margine_sui_comparabili_non_c_e():
    assert mj.decidi({"ok": False, "motivo": "margine_basso"}, None)[0] == "scarta"


def test_decidi_scarta_replica_con_confidenza_alta_ma_non_con_confidenza_bassa():
    assert mj.decidi({"ok": True}, ("replica_probabile", 0.9))[0] == "scarta"
    assert mj.decidi({"ok": True}, ("altra_marca", 0.8))[0] == "scarta"
    assert mj.decidi({"ok": True}, ("replica_probabile", 0.3))[0] == "conferma"


def test_decidi_senza_comparabili_non_verificato_ma_il_falso_scarta_lo_stesso():
    assert mj.decidi(None, None) == ("non_verificato", "comparabili_non_trovati")
    assert mj.decidi(None, ("replica_probabile", 0.9))[0] == "scarta"


def test_tratteni_solo_per_brand_nuovo_con_regola_brand_nuovo(monkeypatch):
    monkeypatch.setattr(mj, "MODA_JEV", True)
    assert mj.tratteni_per_verifica({"brand": "zimmermann"}, "brand_nuovo")
    assert not mj.tratteni_per_verifica({"brand": "zimmermann"}, "giallo_economico")
    assert not mj.tratteni_per_verifica({"brand": "marni"}, "brand_nuovo")
    monkeypatch.setattr(mj, "MODA_JEV", False)
    assert not mj.tratteni_per_verifica({"brand": "zimmermann"}, "brand_nuovo")


def test_righe_messaggio_con_e_senza_comparabili():
    r = mj.righe_messaggio({"rivendita": 140, "n": 7, "margine": 90, "roi": 400, "esempi": [("Abito", 120)], "autenticita": ("originale_plausibile", 0.8)})
    assert any("7 annunci" in x for x in r) and any("sembra originale" in x for x in r)
    r2 = mj.righe_messaggio({"rivendita": None, "autenticita": None})
    assert any("non trovati" in x for x in r2) and any("non verificata" in x for x in r2)


def test_riga_esito_scheda_per_scarto_conferma_e_non_verificato():
    s = mj.riga_esito_scheda({"esito": "scarta", "motivo": "comparabili:margine_basso", "rivendita": 67.5, "n": 6, "margine": 15.5, "roi": 40})
    assert "non avvisato" in s and "68" in s
    f = mj.riga_esito_scheda({"esito": "scarta", "motivo": "foto:replica_probabile", "autenticita": ("replica_probabile", 0.9)})
    assert "replica probabile" in f
    assert "confermato" in mj.riga_esito_scheda({"esito": "conferma", "rivendita": 140, "margine": 90})
    assert "non trovati" in mj.riga_esito_scheda({"esito": "non_verificato"})
