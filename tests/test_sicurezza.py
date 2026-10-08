"""Controlli di sicurezza sulle chiavi (8/10): niente segreti nel repo, niente chiavi nelle URL o nei log."""
import logging
import os
import re
import subprocess

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# forme tipiche di chiavi/token: Google, OpenAI/OpenRouter, Groq, NVIDIA, GitHub, Slack, bot Telegram, session Telethon
_RE_SEGRETI = re.compile(
    r"AIza[0-9A-Za-z_-]{30,}|\bsk-(?=[A-Za-z_-]*\d)[A-Za-z0-9_-]{32,}|gsk_[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}"
    r"|xox[bp]-[A-Za-z0-9-]{10,}|\b[0-9]{8,10}:[A-Za-z0-9_-]{35}\b|\b1BVt[A-Za-z0-9_-]{30,}")


def _file_tracciati():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=RADICE, capture_output=True, text=True, check=True).stdout.split("\n")
    except Exception:
        out = [os.path.relpath(os.path.join(d, f), RADICE) for d, _, fs in os.walk(RADICE) if ".git" not in d for f in fs]
    return [f for f in out if f and not f.endswith((".pyc", ".png", ".jpg"))]


def test_nessun_segreto_nei_file_del_repo():
    trovati = []
    for rel in _file_tracciati():
        try:
            with open(os.path.join(RADICE, rel), encoding="utf-8") as f:
                testo = f.read()
        except Exception:
            continue
        if rel.startswith("tests/test_sicurezza"):
            continue
        for m in _RE_SEGRETI.finditer(testo):
            trovati.append((rel, m.group(0)[:6] + "..."))
    assert not trovati, f"possibili segreti nel repo (mostrati solo i primi caratteri): {trovati}"


def test_gitignore_protegge_env_e_dati_locali():
    righe = open(os.path.join(RADICE, ".gitignore"), encoding="utf-8").read().split("\n")
    for voce in (".env", "*.key", "*.sqlite3", "*.session"):
        assert voce in righe, f"{voce} manca da .gitignore"
    assert "!.env.example" in righe


def test_env_example_ha_solo_nomi_non_valori():
    for riga in open(os.path.join(RADICE, ".env.example"), encoding="utf-8"):
        if riga.strip().startswith("#") or "=" not in riga:
            continue
        for parte in riga.split():
            if "=" in parte:
                nome, valore = parte.split("=", 1)
                assert not valore.strip() or valore.strip() in ("1", "0") or re.fullmatch(r"[0-9.,/_a-z:+-]+|📡|[A-Za-z_/.-]+", valore.strip()), \
                    f"{nome} sembra avere un valore vero in .env.example"


def test_nessuna_chiave_nelle_url_delle_richieste():
    for rel in ("bot/gemini_api.py", "bot/openai_api.py", "bot/panel.py", "bot/riserva_llm.py"):
        codice = open(os.path.join(RADICE, rel), encoding="utf-8").read()
        senza_commenti = "\n".join(r for r in codice.split("\n") if not r.strip().startswith("#"))
        assert not re.search(r"[?&]key=\{|[?&]api_key=\{", senza_commenti), f"{rel}: chiave nella URL (finirebbe nei log)"


def test_httpx_non_logga_le_richieste_a_info():
    import bot.logger  # noqa: F401  (imposta i livelli)
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


def test_i_log_di_telegram_non_stampano_la_url_con_il_token():
    codice = open(os.path.join(RADICE, "bot/telegram_api.py"), encoding="utf-8").read()
    # nei messaggi di log non deve comparire l'URL (api.telegram.org/bot<TOKEN>) ne' l'eccezione intera
    for riga in codice.split("\n"):
        if re.search(r"log\.(warning|error|info)\(", riga):
            assert "TELEGRAM_API" not in riga and "{url" not in riga
