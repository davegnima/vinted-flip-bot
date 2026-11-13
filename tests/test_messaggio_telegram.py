
import main_telethon as m


LISTING = {
    "title": "Shirt dries van noten", "brand": "Dries van Noten", "price": "35", "condition": "Nuovo senza cartellino",
    "material_raw": "Cotone", "color_raw": "Cachi, Multi",
    "uploaded_text": "Proprio adesso, Shirt dries van notes 38 like new cotton, Spedizione",
    "seller_login": "augusta", "seller_feedback_reputation": 4.8, "seller_feedback_count": 25,
    "description": "Shirt dries van notes 38 like new cotton",
    "fair_value": {"fv": 65, "minimo": 35, "massimo": 94, "roi": 86, "semaforo": "🟡", "conf": "media"},
}


def test_caricato_senza_descrizione():
    assert m._riga_caricato_annuncio(LISTING) == "🕒 Caricato: Proprio adesso"
    # da un'ora in su il testo della pagina non e' attendibile (10/11): niente riga
    assert m._riga_caricato_annuncio({"uploaded_text": "un'ora fa, Spedizione"}) is None
    assert m._riga_caricato_annuncio({"uploaded_text": "2 ore fa"}) is None
    assert m._riga_caricato_annuncio({"uploaded_text": "3 minuti fa"}) == "🕒 Caricato: 3 minuti fa"


def test_descrizione_informativa_resta():
    li = dict(LISTING, description="Taglia 38, indossata una volta, ottime condizioni, senza difetti, lavata a 30 gradi")
    assert m._descrizione_utile(li) is not None


