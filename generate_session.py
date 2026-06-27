"""
Script DA ESEGUIRE UNA SOLA VOLTA, sul TUO computer (non su Railway).

Serve per generare una "Session String": una stringa lunga che rappresenta
una sessione di login gia' autenticata. La useremo come variabile
d'ambiente TELEGRAM_SESSION_STRING su Railway, cosi' il bot puo' avviarsi
e restare connesso 24/7 senza che tu debba inserire il codice SMS ogni
volta che il container si riavvia.

PRIMA DI ESEGUIRE QUESTO SCRIPT:
1. Vai su https://my.telegram.org
2. Login con il tuo numero di telefono
3. Vai su "API development tools"
4. Crea una nuova app (qualsiasi nome, es. "VintedFlipOracle")
5. Copia "App api_id" e "App api_hash" -- ti servono qui sotto

ESECUZIONE (sul tuo computer):
    pip install telethon
    python3 generate_session.py

Ti verra' chiesto: api_id, api_hash, numero di telefono (con prefisso,
es. +393331234567), e poi il CODICE che Telegram ti manda via app/SMS.
Se hai la verifica in due passaggi attiva, ti chiedera' anche la password.

Al termine otterrai una stringa lunghissima: copiala e mettila come
variabile d'ambiente TELEGRAM_SESSION_STRING su Railway.

ATTENZIONE: questa stringa equivale a un accesso completo al tuo account
Telegram (come essere loggato su un altro dispositivo). Trattala come
una password: non condividerla in chat, screenshot, o repository pubblici.
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

print("=== Generatore Session String per Telethon ===\n")

api_id = input("Inserisci il tuo api_id (numero, da my.telegram.org): ").strip()
api_hash = input("Inserisci il tuo api_hash (stringa, da my.telegram.org): ").strip()

with TelegramClient(StringSession(), int(api_id), api_hash) as client:
    session_string = client.session.save()
    print("\n" + "=" * 70)
    print("SESSION STRING GENERATA CON SUCCESSO.")
    print("Copiala per intero (e' una sola riga lunga) e usala come")
    print("variabile d'ambiente TELEGRAM_SESSION_STRING su Railway.")
    print("=" * 70 + "\n")
    print(session_string)
    print("\n" + "=" * 70)
    print("NON condividere questa stringa con nessuno: equivale al login")
    print("completo del tuo account Telegram.")
    print("=" * 70)
