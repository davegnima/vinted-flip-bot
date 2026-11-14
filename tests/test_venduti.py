import pytest

from bot import db, venduti_db
from bot.venduti_norma import (a_eur, categoria_da_titolo, condizione_vinted, e_nuovo, normalizza_brand,
                               riga_normalizzata, tipo_da_titolo)


@pytest.fixture(autouse=True)
def db_pulito(tmp_path, monkeypatch):
    db.chiudi()
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "t.sqlite3"))
    yield
    db.chiudi()


def test_brand_alias_accenti_ed_esclusi():
    assert normalizza_brand("Courrèges") == "courreges"
    assert normalizza_brand("Jean Paul Gaultier") == "jean paul gaultier"
    assert normalizza_brand("Max Mara", "Cappotto") == "max mara"
    assert normalizza_brand("Celine") is None
    assert normalizza_brand("Céline") is None
    assert normalizza_brand("MM6 Maison Margiela") is None
    assert normalizza_brand("Y-3") is None
    assert normalizza_brand("?") is None and normalizza_brand("") is None


def test_categoria_e_tipo_dal_titolo():
    assert categoria_da_titolo("Blazer Max Mara in lana") == "giacca"
    assert tipo_da_titolo("Blazer Max Mara in lana", "giacca") == "blazer"
    assert tipo_da_titolo("Giubbotto bomber nero", "giacca") == "giubbotto"
    assert tipo_da_titolo("Trench beige", "cappotto") == "trench"
    # il tipo deve appartenere alla categoria passata
    assert tipo_da_titolo("Trench beige", "giacca") is None
    assert categoria_da_titolo("Oggetto misterioso") is None


def test_condizioni_multilingua_verso_le_cinque_di_vinted():
    assert condizione_vinted("Never worn, with tag") == "nuovo con cartellino"
    assert condizione_vinted("Never worn") == "nuovo senza cartellino"
    assert condizione_vinted("Très bon état") == "ottime condizioni"
    assert condizione_vinted("Excellent condition") == "ottime condizioni"
    assert condizione_vinted("Good condition") == "buone condizioni"
    assert condizione_vinted("Buone condizioni") == "buone condizioni"
    assert condizione_vinted("Fair condition") == "condizioni soddisfacenti"
    assert condizione_vinted("boh") is None and condizione_vinted(None) is None


def test_prezzo_in_eur_e_valuta_ignota():
    assert a_eur(100, "EUR") == 100.0
    assert a_eur(100, "usd") == 88.0
    assert a_eur(100, "XYZ") is None
    assert a_eur(0) is None and a_eur("abc") is None and a_eur(-5) is None


def test_nuovo_dal_titolo_o_dalla_condizione():
    assert e_nuovo("Giacca nuova con cartellino")
    assert e_nuovo("Giacca", "nuovo senza cartellino")
    assert not e_nuovo("Giacca usata", "buone condizioni")


def test_riga_normalizzata_completa_e_incompleta():
    r = riga_normalizzata("vestiaire", "123", "Blazer Max Mara lana", "Max Mara", 300, "USD",
                          condizione="Very good condition", certezza="osservata")
    assert r["brand"] == "max mara" and r["categoria"] == "giacca" and r["tipo"] == "blazer"
    assert r["prezzo_eur"] == 264.0 and r["condizione"] == "ottime condizioni" and r["nuovo"] is False
    assert riga_normalizzata("vestiaire", "1", "Oggetto misterioso", "Max Mara", 10) is None   # senza categoria
    assert riga_normalizzata("vestiaire", "1", "Blazer", "Celine", 10) is None   # brand escluso
    assert riga_normalizzata("vestiaire", "1", "Blazer", "Max Mara", 0) is None   # prezzo non valido
    assert riga_normalizzata("vestiaire", "", "Blazer", "Max Mara", 10) is None   # senza id


def test_archivio_inserisce_senza_doppioni_e_filtra_il_nuovo():
    a = riga_normalizzata("vestiaire", "1", "Blazer Max Mara", "Max Mara", 100)
    b = riga_normalizzata("vestiaire", "2", "Blazer Max Mara nuovo con cartellino", "Max Mara", 300)
    c = riga_normalizzata("ebay", "1", "Gonna Missoni", "Missoni", 50)
    assert venduti_db.inserisci([a, b, c, None]) == 3
    assert venduti_db.inserisci([a]) == 0   # stessa (fonte, id_fonte)
    assert venduti_db.conta_per_fonte() == {"vestiaire": 2, "ebay": 1}
    usati = venduti_db.leggi(brand="max mara")
    assert [r["id_fonte"] for r in usati] == ["1"]
    assert len(venduti_db.leggi(brand="max mara", solo_usato=False)) == 2
    assert venduti_db.leggi(fonte="ebay")[0]["categoria"] == "gonna"
