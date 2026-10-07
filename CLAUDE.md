# Vinted Flip Oracle — guida per Claude

Userbot Telethon che riceve gli annunci dal tracker (`davegnima/Vinted-Notifications`), li valuta con modelli AI e manda il verdetto su Telegram. Obiettivo: trovare capi sottoprezzati (margine >= 50 EUR e ROI >= 100%), pochi falsi, cercando le eccezioni (venditori che prezzano male).

**A inizio sessione (o dopo una compattazione) rileggere `STATO.md`**: stato corrente, controlli da fare e punti aperti. Aggiornarlo a ogni tappa chiusa.

## Regole dell'utente (valgono sempre)
- Niente AI a pagamento: solo piani gratuiti. Non attivare fatturazione, carte o crediti a pagamento da nessuna parte. UNICA ECCEZIONE, voluta dall'utente il 4/10: la sua chiave Google a pagamento (`GEMINI_API_KEY`, variabile Railway; le chiavi gratuite sono in `GEMINI_API_KEYS`) come ultima riserva, con tetto giornaliero `PAGAMENTO_MAX_RICHIESTE_GIORNO`; nessun'altra spesa e nessuna nuova attivazione di fatturazione.
- NIENTE API di Vinted e niente scraping di vinted.it da parte di Claude. Il bot scarica le pagine, Claude no.
- Non toccare `PROXY_LIST` / `PROXY_ESCLUSI` del worker. I proxy dei tracker (lista nella pagina /config) si copiano tra le istanze col consenso dato dall'utente il 7/10.
- Dal 7/10 l'utente NON vuole piu' che gli si chiedano gli ok: fare e avvisare a cose fatte (codice, PR, merge, variabili Railway, servizi, ricerche e configurazione dei tracker). Chiedere solo per spese, chiavi/segreti e azioni irreversibili. Prima di unire una PR controllare la CI: se e' rossa per colpa della PR, sistemarla; se e' rossa anche su main (es. `ruff` del tracker), unire e dirlo.
- Mai scrivere chiavi, password o token in file, commit o PR. Se l'utente incolla una chiave in chat, consigliare di ruotarla.
- Brand: Celine escluso, Missoni resta. Il banword `weekend` nel tracker esclude Weekend Max Mara di proposito.
- Risposte in italiano, brevi, senza domande superflue.

## Pipeline
tracker (messaggio Telegram) -> `process_listing` (`bot/pipeline.py`) -> scrape pagina e foto -> stima rapida fair value (semaforo) -> Occhio (Gemini, vision) -> filtri pre-Cervello -> Cervello (JSON) -> `calcola_verdetto` (`bot/verdetto.py`, deterministico: il modello non calcola margine/ROI/decisione) -> messaggio Telegram.
- Meccanismi con soglie e variabili (fascia Gemini, semaforo, cascate e quote Gemini, riserva OmniRoute e a pagamento, risparmio, preavviso, scrape pagina leggera, pannello, tracciamento vendite, radar): **`docs/pipeline.md`**. Leggere la sezione che serve prima di toccare quel pezzo.
- Cascate Gemini: `bot/gemini_stato.py`. La quota giornaliera free si azzera a mezzanotte di Pacific (07:00 UTC con l'ora legale). Riserva a scalata: `bot/riserva_llm.py`.

## Mappa dei moduli (`bot/`)
- Config e utilita': `config`, `logger`, `costanti`, `testo`, `parsing`, `tempi`.
- Dati e logica pura: `schemas`, `prompts`, `occhio`, `verdetto`, `categorie`, `fair_value`, `filtri`, `comps_filtri`, `skip_report`.
- Stato e rete: `gemini_stato`, `proxy`, `http_clients`, `telegram_api`, `vinted_http`, `db`, `tracciamento`.
- Chiamate esterne: `gemini_api`, `openai_api`, `vinted_scrape`, `vinted_search`, `foto`, `serper_base`, `serper_fonti`, `comps`.
- Flusso: `pipeline`, `scheda` (messaggi Telegram), `panel`, `riserva_llm`, `radar`.
- `main_telethon.py`: client Telethon, comandi, `main()` e un blocco di re-export (i test usano `m.NOME`).
- Direzione degli import: config/logger -> logica pura -> stato/client -> pipeline -> main. Niente import circolari.
- I client HTTP riassegnati a runtime si leggono come `hc._client_generico`, `hc._client_telegram`, `hc._CLIENT_VINTED_AUTH`: mai importarli per nome.

## Test e CI
- `python3 -m pytest -q` e `python3 -m pyflakes main_telethon.py bot`; la CI (`.github/workflows/ci.yml`) fa lo stesso su Python 3.13. `tests/test_struttura.py` importa ogni modulo da solo: un import circolare lo rompe.
- Branch di lavoro `claude/...`, PR verso `main`, squash merge.

## Railway e dove guardare
- Progetto "Vinted Flip Oracle" `cd06f689-76ef-4b17-aee8-0c04dc03a4d9`, ambiente `6f828acc-20fc-4858-a48b-3f63f57a5a03`. Servizi: `worker` `7f856e1e-dad7-4798-90de-ac6ca77e5756`, `omniroute` `091a30ad-e994-4486-ab56-6f99b2b18521`.
- Progetto tracker "loyal-beauty" `6d89993f-2a71-4ff7-9746-83ed327195f9`, servizio `vinted-notifications` (ricerche: pagina `/queries`, modifica con POST a `/update_query/<id>`); secondo tracker `vinted-radar` `96bfce5d-2015-48a8-bfb1-7a62043907e3`.
- OmniRoute: dashboard con login; la password sta nelle variabili del servizio `omniroute`, non in questo file.
- Railway fa il deploy da `main` a ogni merge (circa 1,5 minuti). Variabili: `.env.example` (solo i nomi).

## Log (dettaglio e filtri in `docs/log.md`)
- Filtrare SEMPRE con `filter` e finestre strette, `limit` 20-40 per controlli puntuali; per analisi su ore `limit` 500 (finisce in file solo oltre ~80.000 caratteri: allargare il filtro) ed elaborare con `python3`, mai incollare righe a mano.
- Filtri base: `"| ESITO |"`, `"SKIP non inviato"`, `Traceback`, `"GEMINI_USO"`, `"RISERVA |"`, `"PREAVVISO |"`, `"RICONTROLLO LAMPO"`, `"RADAR |"`. Dopo un deploy solo righe successive a `"Vinted Oracle avviato"`. Con traffico basso dirlo e aspettare.

## Modelli dei lavori ripetuti
- `docs/modelli/` (PR e merge, analisi dei log, variabili Railway, aggiornamento di `STATO.md`) e `docs/recap.md` (recap mattutino): seguirli quando il lavoro e' quello.

## Convenzioni
- Codice e commenti in italiano, stile come quello vicino. Niente modifiche a `prompts.py` senza motivo: le calibrazioni per brand sono frutto di dati reali.
- Il pannello e la riserva usano `@c` in coda al modello per il prompt compatto; il suffisso non va mai al gateway.
- Verificare la CI prima di ogni merge; non fare push forzati su branch altrui.
