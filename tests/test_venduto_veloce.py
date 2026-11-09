from bot import tracciamento as t


def test_venduto_veloce_con_margine_del_verdetto():
    assert t.venduto_veloce_da_inviare({"margine": "55", "fv": 90}, 30, "AFFARE")
    assert not t.venduto_veloce_da_inviare({"margine": "39", "fv": 90}, 30, "AFFARE")


def test_venduto_veloce_senza_verdetto_usa_fair_value_meno_prezzo():
    assert t.margine_venduto_veloce({"fv": 80}, 30) == 50
    assert t.venduto_veloce_da_inviare({"fv": 80}, 30, "MEDIO AFFARE")
    assert not t.venduto_veloce_da_inviare({"fv": 60}, 30, "AFFARE")


def test_venduto_veloce_solo_classi_veloci_e_una_volta():
    assert not t.venduto_veloce_da_inviare({"fv": 200}, 30, "NORMALE")
    assert not t.venduto_veloce_da_inviare({"fv": 200}, 30, None)
    assert not t.venduto_veloce_da_inviare({"fv": 200, "_veloce_inviato": True}, 30, "AFFARE")
    assert not t.venduto_veloce_da_inviare({}, 30, "AFFARE")


def test_testo_venduto_veloce():
    ctx = {"fv": 90, "esito": "SKIP_SOLO_SEMAFORO", "sem": "🟢", "_titolo": "Giacca Burberry", "preavviso": "no"}
    testo = t.testo_venduto_veloce("1", "https://www.vinted.it/items/1", "Burberry", 30, 140, "AFFARE", ctx)
    assert "Venduto in 2 min" in testo and "margine ~60 €" in testo and "NON avvisato" in testo
    ctx["preavviso"] = "si"
    assert "NON avvisato" not in t.testo_venduto_veloce("1", "u", "B", 30, 140, "AFFARE", ctx)


def test_venduto_veloce_rossi_e_gialli_anche_sotto_soglia():
    assert t.venduto_veloce_da_inviare({"fv": 40, "sem": "🔴"}, 30, "AFFARE")
    assert t.venduto_veloce_da_inviare({"margine": "5", "sem": "🟡"}, 30, "MEDIO AFFARE")
    assert not t.venduto_veloce_da_inviare({"fv": 40, "sem": "🟢"}, 30, "AFFARE")


def test_testo_venduto_veloce_riga_jev_gemini_legit():
    ctx = {"esito": "SOLO_SEMAFORO", "sem": "🟢", "fv": 148, "margine": 138, "_jev": 250, "_gem": 240,
           "_legit_jev": t._legit_breve("🔐 Originalità: ✅ LEGIT (sembra originale) · Gemini 90%")}
    txt = t.testo_venduto_veloce("1", "https://x", "Balenciaga", 10, 60, "AFFARE", ctx)
    assert "🔎 Jev ~250 € · Gemini 240 € · legit: ✅ LEGIT" in txt
    assert "margine n/d" in t.testo_venduto_veloce("1", "https://x", "X", 10, 60, "AFFARE", {"sem": "🔴"})


def test_didascalia_preavviso_con_query_lunga_non_spezza_il_markdown():
    from bot.scheda import didascalia_verdetto
    url = "https://www.vinted.it/catalog?" + "brand_ids%5B%5D=1189&" * 40
    testo = "\n".join(["⚡ 🟢 ~+86 € · *💶 20,00 € · 🏷️ Fendi*", "📊 Fair value ~106 €", "[vedi su Vinted](https://x/1)",
                       f"🔎 Query: [Contemporary2 Fendi]({url})", "⏱ telegram→preavviso 23s", "_preavviso del semaforo: " + "x " * 200 + "_"])
    out = didascalia_verdetto(testo)
    assert len(out) <= 1024 and "🔎 Query" not in out and out.count("[") == out.count("](")


def test_riga_preavviso_interrotta_dal_riavvio():
    from bot.scheda import riga_scarto_preavviso
    assert "riavvio" in riga_scarto_preavviso(None, None, interrotta=True, riavvio=True)
    assert "errore" in riga_scarto_preavviso(None, None, interrotta=True)


def test_lampo_parte_anche_senza_categoria_nel_titolo(monkeypatch):
    import asyncio
    import bot.pipeline as pl
    chiamate = []

    async def finto_invio(*a, **k):
        chiamate.append(1)
    monkeypatch.setattr(pl, "invia_preavviso", finto_invio)
    fv = {"semaforo": "🟢", "margine": 66.0, "conf": "bassa", "fonte_categoria": "nessuna", "fv": 71, "brand": "jean paul gaultier"}
    monkeypatch.setattr(pl, "stima_fair_value", lambda li: fv)
    li = {"title": "Tunique", "brand": "Jean Paul Gaultier", "price": "5"}

    async def prova(soglia):
        monkeypatch.setattr(pl, "LAMPO_SENZA_CATEGORIA_MARGINE_MIN", soglia)
        stato = {}
        pl._preavviso_lampo(li, "https://www.vinted.it/items/1-x", b"x", None, None, stato)
        if stato.get("task_preavviso"):
            await stato["task_preavviso"]
        return stato
    assert asyncio.run(prova(50)).get("preavviso_lampo") and chiamate
    assert not asyncio.run(prova(80)).get("preavviso_lampo")
    assert not asyncio.run(prova(0)).get("preavviso_lampo")
