"""Parser dei comp Vinted sul markup dal 25/10/2026: titolo e prezzo nel title= del link overlay (campione reale
dai log 'COMPS PAGINA CAMPIONE'). Il markup con alt= e taglia resta come riserva."""
from bot.comps_filtri import _articoli_vinted, _estrai_articoli_da_alt_vinted, _estrai_mappa_url_comp_vinted

HTML_NUOVO = (
    '<img alt="" class="web_ui__Image__content" data-testid="product-item-id-10533215281--image--img"/></div></div>'
    '<a href="/items/10533215281-fujifilm-finepix-av200-black-digital-camera?referrer=catalog" '
    'class="NoC3Da_new-item-box__overlay" data-testid="product-item-id-10533215281--overlay-link" '
    'title="Fujifilm finepix av200 black digital camera, Brand: FUJIFILM, Condizioni: Buone, 40.00 €, 42.70 €" '
    'target="_self" rel="noreferrer"><div></div></a>'
    '<a href="/items/10533349942-accesorio-de-nintendo?referrer=catalog" '
    'data-testid="product-item-id-10533349942--overlay-link" '
    'title="Accesorio de Nintendo, Brand: Nintendo, Condizioni: Ottime, 50.00 €, 53.20 €" target="_self"><div></div></a>'
)

HTML_VECCHIO = (
    '<img alt="Manteau Jean Paul Gaultier, Brand: Jean Paul Gaultier, Condizioni: Ottime, Taglia: M / IT 42, '
    '140.00 €, 147.70 €" data-testid="product-item-id-555--image--img"/>'
)


def test_titolo_nuovo_con_id_titolo_e_primo_prezzo():
    assert _articoli_vinted(HTML_NUOVO) == [
        ("10533215281", "Fujifilm finepix av200 black digital camera", "40.00"),
        ("10533349942", "Accesorio de Nintendo", "50.00"),
    ]


def test_output_testuale_e_link_per_il_markup_nuovo():
    testo = _estrai_articoli_da_alt_vinted(HTML_NUOVO)
    assert testo.splitlines() == [
        "- Fujifilm finepix av200 black digital camera — €40.00",
        "- Accesorio de Nintendo — €50.00",
    ]
    mappa = _estrai_mappa_url_comp_vinted(HTML_NUOVO)
    assert mappa[("fujifilm finepix av200 black digital camera", "40.00")] == "https://www.vinted.it/items/10533215281"


def test_markup_vecchio_con_alt_e_taglia_resta_riserva():
    assert _articoli_vinted(HTML_VECCHIO) == [(None, "Manteau Jean Paul Gaultier", "140.00")]
    assert _estrai_articoli_da_alt_vinted(HTML_VECCHIO) == "- Manteau Jean Paul Gaultier — €140.00"


def test_pagina_senza_articoli_non_inventa_nulla():
    assert "Nessun articolo trovato" in _estrai_articoli_da_alt_vinted("<html></html>")
