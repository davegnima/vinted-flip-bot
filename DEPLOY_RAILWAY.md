# Vinted Flip Oracle Bot — Guida Telethon (userbot)

Perché questo cambio: la Telegram Bot API **non consegna ai bot i
messaggi scritti da altri bot**. Dato che "Vinted Tracker" è un bot,
il tuo bot precedente non poteva mai vederne i messaggi, a prescindere
da gruppo, Topics, ruoli admin o privacy mode. Questa versione usa un
**userbot** (Telethon): uno script che si collega come il TUO account
Telegram personale, che vede tutto come una persona normale — bot
compresi.

La parte che INVIA i report finali resta il bot "Vinted Notification"
via Bot API normale (questo continua a funzionare, l'invio non ha la
stessa limitazione della ricezione).

---

## Passo 1 — Ottieni api_id e api_hash da Telegram

1. Vai su **my.telegram.org** (dal browser, sul tuo computer)
2. Accedi con il tuo numero di telefono (ti manda un codice via Telegram)
3. Clicca **API development tools**
4. Compila il form: "App title" e "Short name" possono essere qualsiasi
   cosa (es. "VintedFlipOracle"), "Platform" scegli "Desktop"
5. Clicca **Create application**
6. Ti mostra **App api_id** (un numero) e **App api_hash** (una stringa
   lunga) — copia entrambi, ti servono al passo 2

## Passo 2 — Genera la Session String (UNA SOLA VOLTA, sul tuo computer)

Questo passaggio richiede di eseguire uno script Python **sul tuo
computer** (non su Railway), perché ti chiederà interattivamente il
codice SMS/app che Telegram ti manda per autenticarti. Una volta fatto,
non dovrai più rifarlo.

1. Sul tuo computer, apri un terminale
2. Installa Telethon:
   ```
   pip install telethon
   ```
3. Scarica il file `generate_session.py` (te l'ho fornito separatamente)
4. Eseguilo:
   ```
   python3 generate_session.py
   ```
5. Ti chiederà `api_id` e `api_hash` (quelli del Passo 1)
6. Poi ti chiederà il tuo numero di telefono con prefisso internazionale
   (es. `+393331234567`)
7. Telegram ti manda un codice (via app Telegram stessa, non SMS di
   solito) — inseriscilo quando richiesto
8. Se hai la verifica in due passaggi attiva, ti chiede anche quella
   password
9. Al termine, lo script stampa una **stringa lunghissima** — è la tua
   Session String. Copiala per intero (è un'unica riga, anche se va a
   capo nel terminale)

**Importante**: questa stringa equivale a un login completo al tuo
account Telegram. Non condividerla in chat, screenshot, o repository
pubblici — va solo nelle variabili d'ambiente di Railway (Passo 5).

## Passo 3 — Recupera l'ID del gruppo (se non lo hai già)

Hai già questo dato da prima: il gruppo "Dadegnima, Vinted Notification
e Vinted Tracker" ha id `-1003919349127` (con il formato `-100...`
corretto). Se in futuro serve riverificarlo, usa RawDataBot o condividi
la chat con lui come hai già fatto.

## Passo 4 — Aggiorna i file su GitHub

Nel tuo repo `vinted-flip-bot` su GitHub, carica/sostituisci questi file:

- `main_telethon.py` (nuovo file, è lo script principale ora)
- `generate_session.py` (solo per riferimento/uso futuro)
- `requirements.txt` (aggiornato, ora include anche `telethon`)
- `Procfile` (aggiornato, ora punta a `main_telethon.py`)

Il vecchio `main.py` (versione Bot API) puoi lasciarlo nel repo per
riferimento, o eliminarlo — non viene più eseguito perché il Procfile
ora punta al nuovo file.

## Passo 5 — Aggiorna le variabili d'ambiente su Railway

Vai su Railway → progetto → service **worker** → tab **Variables**.

**Variabili da AGGIUNGERE (nuove):**
```
TELEGRAM_API_ID         → il numero ottenuto al Passo 1
TELEGRAM_API_HASH       → la stringa ottenuta al Passo 1
TELEGRAM_SESSION_STRING → la stringa lunga ottenuta al Passo 2
```

**Variabili che RESTANO (già presenti, non cambiano):**
```
TELEGRAM_GROUP_ID       → -1003919349127
TELEGRAM_BOT_TOKEN      → il token del bot "Vinted Notification"
TELEGRAM_OWNER_CHAT_ID  → 501041125
ANTHROPIC_API_KEY       → la tua key Claude
GEMINI_API_KEY          → la tua key Gemini
```

Salva tutte le variabili. Railway farà un nuovo deploy automaticamente
(rileverà il nuovo Procfile e installerà anche `telethon` da
requirements.txt durante il build).

## Passo 6 — Verifica nei log

Tab **Deployments** → ultimo deployment (dovrebbe essere "Active") →
**View Logs**. Dovresti vedere:

```
... | INFO | Vinted Flip Oracle Bot (Telethon) avviato. In ascolto sul gruppo -1003919349127
```

Se Telethon ha problemi con la Session String (es. scaduta o inserita
male), vedrai un errore di autenticazione qui — in quel caso va
rigenerata la Session String ripetendo il Passo 2.

## Passo 7 — Test reale

Aspetta la prossima notifica vera di "Vinted Tracker" in uno dei topic
del gruppo. Questa volta, essendo l'userbot ad ascoltare (non un bot),
il messaggio dovrebbe essere intercettato correttamente. Controlla i
log per la riga:

```
Nuovo annuncio rilevato: <titolo> | url=...
```

Se la vedi, la pipeline (scraping → Gemini → Claude → invio report)
procede esattamente come nella versione precedente, e riceverai il
report completo in chat privata con @VintedGnimaBot.

## Note di sicurezza importanti

- La **Session String** è equivalente a una password del tuo account
  Telegram personale. Se sospetti che sia stata esposta, puoi
  revocarla da Telegram stesso: Impostazioni → Dispositivi → trova la
  sessione "Telethon"/sconosciuta → Termina sessione. Questo invalida
  la stringa e dovrai rigenerarla.
- Usando un userbot, agli occhi di Telegram è come se tu avessi un
  "dispositivo" sempre connesso e in ascolto. Questo è un uso comune
  e diffuso (molte automazioni personali lo fanno), ma tecnicamente
  non è il caso d'uso "ufficiale" previsto per i bot — rischio basso
  per un utilizzo personale come questo, ma da sapere.
- Se in futuro disconnetti/rigeneri la sessione, ricorda di aggiornare
  anche la variabile `TELEGRAM_SESSION_STRING` su Railway.

## Costi aggiuntivi

Nessuno: Telethon stesso è gratuito (libreria open source), e l'userbot
non consuma "messaggi" o ha costi propri — usa la tua connessione
Telegram normale. I costi restano solo quelli già noti: Railway
(~gratis nel free tier per questo carico), Claude e Gemini per
ogni valutazione (~€0.07-0.10/check).
