from datetime import datetime, timezone

from bot import gemini_stato as gs


def _ts(g, h, m=0):
    return datetime(2026, 10, g, h, m, tzinfo=timezone.utc).timestamp()


def test_reset_quota_e_mezzanotte_pacific():
    # 4/10 18:30 UTC (ora legale, UTC-7): il prossimo reset e' il 5/10 alle 07:00 UTC
    assert gs.prossimo_reset_quota_gemini(_ts(4, 18, 30)) == _ts(5, 7)
    # subito dopo il reset si aspetta quello del giorno dopo
    assert gs.prossimo_reset_quota_gemini(_ts(4, 7, 1)) == _ts(5, 7)


def test_cooldown_lungo_della_regola_vecchia_non_si_ripristina():
    adesso = _ts(4, 18, 30)
    assert gs.cooldown_quota_affidabile(adesso + 45, adesso)                        # limite al minuto
    assert gs.cooldown_quota_affidabile(_ts(5, 7) + 60, adesso)                      # finisce al reset Pacific
    assert not gs.cooldown_quota_affidabile(_ts(4, 23, 59), adesso)                  # "retry in 23h" di Google


def test_quota_giornaliera_segnata_fino_al_reset(monkeypatch):
    adesso = _ts(4, 18, 30)
    monkeypatch.setattr(gs.time, "time", lambda: adesso)
    monkeypatch.setattr(gs.db, "salva_quota_gemini", lambda *a, **k: None)
    gs._gemini_key_quota_esaurita_fino.clear()
    gs._gemini_segna_key_quota_esaurita("chiave-x", "gemini-3.5-flash", 23 * 3600 + 14 * 60)
    fino = gs._gemini_key_quota_esaurita_fino[("chiave-x", "gemini-3.5-flash")]
    assert abs(fino - (_ts(5, 7) + 60)) <= 5
    gs._gemini_key_quota_esaurita_fino.clear()


def test_errore_key_non_valida_riconosciuto():
    corpo = '{"error": {"code": 401, "message": "The bound service account is deleted or disabled.", "status": "UNAUTHENTICATED"}}'
    assert gs._gemini_e_errore_key_non_valida(401, corpo)
    assert gs._gemini_e_errore_key_non_valida(403, '{"error": {"status": "PERMISSION_DENIED"}}')
    assert not gs._gemini_e_errore_key_non_valida(429, corpo)
    assert not gs._gemini_e_errore_key_non_valida(401, "")


def test_key_non_valida_vale_per_ogni_modello_e_la_rotazione_la_salta(monkeypatch):
    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["morta", "viva"])
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {})
    monkeypatch.setattr(gs, "_gemini_key_index", [0])
    monkeypatch.setattr(gs.db, "salva_quota_gemini", lambda *a, **k: None)
    gs._gemini_segna_key_non_valida("morta")
    assert gs._gemini_key_in_quota_esaurita("morta", "gemini-3.5-flash")
    assert gs._gemini_key_in_quota_esaurita("morta", "gemini-3.1-flash-lite")
    assert not gs._gemini_key_in_quota_esaurita("viva", "gemini-3.5-flash")
    assert gs._gemini_key_attuale("gemini-3.5-flash") == "viva"


def test_chiama_gemini_passa_alla_key_valida_dopo_un_401(monkeypatch):
    import asyncio
    import httpx
    from bot import gemini_api as ga
    from bot import http_clients as hc

    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["morta", "viva"])
    monkeypatch.setattr(ga, "GEMINI_API_KEYS", ["morta", "viva"])
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {})
    monkeypatch.setattr(gs, "_gemini_key_index", [0])
    monkeypatch.setattr(gs.db, "salva_quota_gemini", lambda *a, **k: None)
    chiavi_usate = []

    class Finto:
        async def post(self, url, headers=None, json=None, timeout=None):
            k = headers["x-goog-api-key"]
            chiavi_usate.append(k)
            req = httpx.Request("POST", url)
            if k == "morta":
                return httpx.Response(401, request=req, text='{"error":{"status":"UNAUTHENTICATED","message":"service account deleted"}}')
            return httpx.Response(200, request=req, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    monkeypatch.setattr(hc, "_client_generico", Finto())
    testo, _, _ = asyncio.run(ga.chiama_gemini("s", "u", max_retries=3))
    assert testo == "ok"
    assert chiavi_usate == ["morta", "viva"]


def test_timeout_di_fila_mettono_la_fase_in_pausa(monkeypatch):
    monkeypatch.setattr(gs, "_gemini_timeout_di_fila", {})
    monkeypatch.setattr(gs, "_gemini_pausa_timeout_fino", {})
    assert not gs.gemini_segna_timeout("cervello")          # il primo non basta
    assert not gs.gemini_in_pausa_timeout("cervello")
    assert gs.gemini_segna_timeout("cervello")              # il secondo di fila: pausa
    assert gs.gemini_in_pausa_timeout("cervello") and not gs.gemini_in_pausa_timeout("occhio")
    gs.gemini_timeout_azzera("occhio")
    from bot import riserva_llm
    assert riserva_llm.gemini_in_pausa("cervello")


def test_chiama_gemini_dopo_due_timeout_smette_di_ritentare(monkeypatch):
    import asyncio
    import httpx
    from bot import gemini_api as ga
    from bot import http_clients as hc

    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["k1", "k2"])
    monkeypatch.setattr(ga, "GEMINI_API_KEYS", ["k1", "k2"])
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {})
    monkeypatch.setattr(gs, "_gemini_timeout_di_fila", {})
    monkeypatch.setattr(gs, "_gemini_pausa_timeout_fino", {})
    monkeypatch.setattr(ga, "GEMINI_BACKOFF_MAX_S", 0.01)
    chiamate = []

    class Finto:
        async def post(self, url, headers=None, json=None, timeout=None):
            chiamate.append(1)
            raise httpx.ReadTimeout("lento")

    monkeypatch.setattr(hc, "_client_generico", Finto())
    testo, _, _ = asyncio.run(ga.chiama_gemini("s", "u", max_retries=6))
    assert testo.startswith("[ERRORE")
    assert len(chiamate) == 2          # dopo 2 timeout di fila la fase e' in pausa: niente altri tentativi
