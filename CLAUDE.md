# Vinted Flip Oracle — guida per Claude

Userbot Telethon che riceve gli annunci dal tracker (`davegnima/Vinted-Notifications`), li valuta con modelli AI e manda il verdetto su Telegram. Obiettivo: trovare capi sottoprezzati (margine >= 50 EUR e ROI >= 100%), pochi falsi, cercando le eccezioni (venditori che prezzano male).

**A inizio sessione (o dopo una compattazione) rileggere `STATO.md`**: stato corrente, controlli da fare e punti aperti. Aggiornarlo a ogni tappa chiusa.

## Regole dell'utente (valgono sempre)
- Niente AI a pagamento: solo piani gratuiti. Non attivare fatturazione, carte o crediti a pagamento da nessuna parte.
- NIENTE API di Vinted e niente scraping di vinted.it da parte di Claude. Il bot scarica le pagine, Claude no.
- Non toccare `PROXY_LIST` / `PROXY_ESCLUSI`.
- Non modificare codice, PR, variabili Railway o ricerche del tracker senza ok esplicito dell'utente (salvo che l'utente lo chieda nel messaggio). Prima di unire una PR controllare che la CI sia verde.
- Mai scrivere chiavi, password o token in file, commit o PR. Se l'utente incolla una chiave in chat, consigliare di ruotarla.
- Brand: Celine escluso, Missoni resta. Il banword `weekend` nel tracker esclude Weekend Max Mara di proposito.
- Risposte in italiano, brevi, senza domande superflue.

## Pipeline
tracker (messaggio Telegram) -> `process_listing` (`bot/pipeline.py`) -> scrape pagina e foto -> stima rapida fair value -> Occhio (Gemini, vision) -> filtri pre-Cervello -> Cervello (JSON; mediana di 3 campioni solo per COMPRA/TRATTA) -> `calcola_verdetto` (deterministico: decisione da margine e ROI) -> messaggio Telegram.
- Il modello non calcola margine/ROI/decisione: lo fa Python (`bot/verdetto.py`).
- Fascia Gemini scelta prima dell'Occhio da `ruoli_gemini` (stima rapida verde/gialla = alta; rossa = alta solo se prezzo >= `GEMINI_SOGLIA_PREZZO_ALTO`; stima a confidenza bassa = si sceglie dal prezzo).
- Stima rapida (`stima_fair_value`): ogni annuncio con brand ha un semaforo. Ordine: tabella dati -> appreso dai verdetti -> livello del brand x fattore categoria -> livello di default. Categoria da titolo, descrizione o catalogo Vinted (mappa che si impara sola: `CATALOGO_CATEGORIE_FILE`). Stime a confidenza bassa: soglie del semaforo x `FAIR_VALUE_RIGORE_BASSA`; voci non apprese x `FAIR_VALUE_TARATURA_GLOBALE` (1,20; Missoni prima linea +10%, Cucinelli +15% in piu').
- Cascate Gemini per fase, dal modello migliore al piu' leggero: `bot/gemini_stato.py`. 4 account Google, quote per (key, modello).
- Riserva a scalata via OmniRoute (`bot/riserva_llm.py`): spenta finche' `RISERVA_OCCHIO_MODELLI` / `RISERVA_CERVELLO_MODELLI` sono vuote.
- Preavviso (`valuta_preavviso` in `bot/fair_value.py`): un album con TUTTE le foto e il semaforo parte nel gruppo COMPRA (`TELEGRAM_ALERT_CHAT_ID`, con suono) appena le foto sono scaricate, se la stima rapida e' promettente; a fine analisi lo stesso messaggio viene AGGIORNATO col verdetto (didascalia, max 1024 caratteri), senza altri messaggi nel gruppo (senza gruppo, la scheda in chat principale diventa push) (soglie `PREAVVISO_*`, spento con `PREAVVISO_ATTIVO=0`); non cambia il semaforo.
- Pannello in ombra (`bot/panel.py`): modelli extra via OmniRoute, solo log `PANEL | ...`, mai nel verdetto.
- SQLite (`bot/db.py`, `/data/vinted_bot.sqlite3`): quote Gemini e eventi. I log restano la fonte del recap.

## Mappa dei moduli (`bot/`)
- Config e utilita': `config`, `logger`, `costanti`, `testo`, `parsing`, `tempi`.
- Dati e logica pura: `schemas`, `prompts`, `occhio`, `verdetto`, `categorie`, `fair_value`, `filtri`, `comps_filtri`, `skip_report`.
- Stato e rete: `gemini_stato`, `proxy`, `http_clients`, `telegram_api`, `vinted_http`, `db`, `tracciamento`.
- Chiamate esterne: `gemini_api`, `openai_api`, `vinted_scrape`, `vinted_search`, `foto`, `serper_base`, `serper_fonti`, `comps`.
- Flusso: `pipeline`, `scheda` (messaggi Telegram), `panel`, `riserva_llm`.
- `main_telethon.py`: client Telethon, comandi, `main()` e un blocco di re-export (i test usano `m.NOME`).
- Direzione degli import: config/logger -> logica pura -> stato/client -> pipeline -> main. Niente import circolari.
- I client HTTP riassegnati a runtime si leggono come `hc._client_generico`, `hc._client_telegram`, `hc._CLIENT_VINTED_AUTH`: mai importarli per nome.

## Test e CI
- `python3 -m pytest -q` (105 test) e `python3 -m pyflakes main_telethon.py bot` (nomi non definiti). La CI (`.github/workflows/ci.yml`) fa lo stesso su Python 3.13.
- `tests/test_struttura.py` importa ogni modulo da solo: un import circolare lo rompe.
- Railway fa il deploy da `main` a ogni merge (circa 1,5 minuti). Branch di lavoro: `claude/...`, PR verso `main`, squash merge.

## Railway e dove guardare
- Progetto "Vinted Flip Oracle" `cd06f689-76ef-4b17-aee8-0c04dc03a4d9`, ambiente `6f828acc-20fc-4858-a48b-3f63f57a5a03`. Servizi: `worker` `7f856e1e-dad7-4798-90de-ac6ca77e5756`, `omniroute` `091a30ad-e994-4486-ab56-6f99b2b18521`.
- Progetto tracker "loyal-beauty" `6d89993f-2a71-4ff7-9746-83ed327195f9`, servizio `vinted-notifications`. Le sue ricerche si leggono (sola lettura) dalla pagina `/queries` del suo dominio pubblico; si modificano con POST a `/update_query/<id>` (campi `query`, `query_name`) solo se l'utente lo chiede.
- OmniRoute (gateway AI): il dashboard ha login con password; la password sta nelle variabili del servizio `omniroute`, non in questo file.

## Come leggere i log senza sprecare token
I log sono enormi. Regole:
1. Filtrare SEMPRE con `filter` e finestre di tempo strette (`startDate`), `limit` basso (20-40) per controlli puntuali.
2. Per analisi su ore: `limit` 500 e il risultato finisce in un file; elaborarlo con `python3`/`jq`, non leggerlo a mano.
   - Il risultato viene salvato in un file SOLO se supera circa 80.000 caratteri; altrimenti arriva inline nella conversazione (costoso e impossibile da elaborare con uno script). Per averlo sempre in file, allargare il filtro: per esempio `"| ESITO |" OR "classe=AFFARE" OR "classe=MEDIO AFFARE" OR "classe=NORMALE" OR "classe=NON AFFARE"` su finestre di 3-6 ore (una finestra notturna con poche righe resta comunque piccola: in quel caso aggiungere anche `"PANEL |"` oppure accorpare notte e sera in una finestra piu' larga).
   - Mai incollare a mano nello script righe lette in conversazione: se serve un conteggio esatto, rifare la richiesta con il filtro allargato.
3. Cercare per id annuncio: `filter` con l'id tra virgolette.
4. Filtri utili (parole esatte nei log):
   - esiti per annuncio: `"| ESITO |"`; saltati senza messaggio: `"SKIP non inviato"`
   - errori: `Traceback`, `"Markdown fallita"`, `"FALLITA"`
   - modelli: `"GEMINI_USO"`, `"RISERVA |"`, `"PANEL |"`, `"PANEL HTTP"`
   - vendite rapide: `"RICONTROLLO LAMPO"`; preavviso push (una riga per annuncio, con semaforo, regola e caratteristiche: categoria, condizione, materiale, taglia, lingua, n. foto, venditore, ora): `"PREAVVISO |"`; le righe `RICONTROLLO LAMPO` e `PREAVVISO` portano `preferiti`/`visite` (letti dalla pagina, nomi dei campi da verificare); le righe `ESITO` portano `item=` per incrociarle con `PREAVVISO` e `RICONTROLLO LAMPO`
   - banda proxy: `"RIEPILOGO BANDA"`
5. Dopo un deploy controllare solo righe successive all'avvio (`"Vinted Oracle avviato"` riporta la versione).
6. Se non arrivano annunci analizzati (traffico basso, es. sabato sera) dirlo e aspettare, non rileggere in loop.

## Convenzioni
- Codice e commenti in italiano, stile come quello vicino. Niente modifiche a `prompts.py` senza motivo: le calibrazioni per brand sono frutto di dati reali.
- Il pannello e la riserva usano `@c` in coda al modello per il prompt compatto; il suffisso non va mai al gateway.
- Verificare la CI prima di ogni merge; non fare push forzati su branch altrui.
