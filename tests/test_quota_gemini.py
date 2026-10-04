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
