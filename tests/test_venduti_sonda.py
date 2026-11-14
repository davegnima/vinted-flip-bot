import json

from bot.venduti_sonda import analizza_ebay, analizza_vestiaire, e_bloccato


def test_bloccato_da_status_e_da_redirect():
    assert e_bloccato(403, "https://www.ebay.it/sch/i.html")
    assert e_bloccato(200, "https://signin.ebay.it/ws/eBayISAPI.dll?SignIn")
    assert e_bloccato(200, "https://www.ebay.de/splashui/challenge?ap=1")
    assert not e_bloccato(200, "https://www.ebay.it/sch/i.html?_nkw=prada")


def test_ebay_redirect_a_login_non_passa():
    r = analizza_ebay("<html></html>", "https://signin.ebay.it/x", 200)
    assert r["esito"] == "bloccato"


def test_ebay_conta_articoli_barrati_e_venduti():
    riga = '<li class="s-item "><span class="s-item__price">EUR 50</span><span>Venduto</span></li>'
    html = riga * 6 + '<span class="s-item__price STRIKETHROUGH">EUR 90</span>'
    r = analizza_ebay(html, "https://www.ebay.it/sch/i.html", 200)
    assert r["esito"] == "passato"
    assert r["articoli"] == 6 and r["barrati"] >= 1


def test_ebay_pagina_senza_venduti():
    html = '<li class="s-item "><span class="s-item__price">EUR 50</span></li>' * 6
    assert analizza_ebay(html, "https://www.ebay.it/sch/i.html", 200)["esito"] == "senza_venduti"


def _next(dati):
    return '<html><script id="__NEXT_DATA__" type="application/json">%s</script></html>' % json.dumps(dati)


def test_vestiaire_prodotti_in_next_data_con_campo_sold():
    dati = {"props": {"pageProps": {"items": [
        {"brand": "Prada", "name": "Giacca", "price": {"amount": 300}, "sold": True},
        {"brand": "Prada", "name": "Borsa", "price": {"amount": 500}, "sold": True}]}}}
    r = analizza_vestiaire(_next(dati), "https://it.vestiairecollective.com/search/", 200)
    assert r["esito"] == "passato" and r["articoli"] == 2 and r["con_campo_sold"] == 2


def test_vestiaire_senza_next_data():
    r = analizza_vestiaire("<html>nulla</html>", "https://it.vestiairecollective.com/search/", 200)
    assert r["esito"] == "senza_next_data"


def test_vestiaire_prodotti_senza_sold():
    dati = {"items": [{"brand": "Prada", "name": "Giacca", "price": 300}]}
    r = analizza_vestiaire(_next(dati), "https://it.vestiairecollective.com/search/", 200)
    assert r["esito"] == "senza_venduti"
