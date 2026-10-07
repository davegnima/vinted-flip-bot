# Vinted Flip Oracle — guida per Claude

Userbot Telethon che riceve gli annunci dal tracker (`davegnima/Vinted-Notifications`), li valuta con modelli AI e manda il verdetto su Telegram. Obiettivo: trovare capi sottoprezzati (margine >= 50 EUR e ROI >= 100%), pochi falsi, cercando le eccezioni (venditori che prezzano male).

**A inizio sessione (o dopo una compattazione) rileggere `STATO.md`**: stato corrente, controlli da fare e punti aperti. Aggiornarlo a ogni tappa chiusa.

## Regole dell'utente (valgono sempre; le prime 3 contano di piu')
1. Non chiedere ok: fare e avvisare a cose fatte (codice, PR, merge, variabili Railway, servizi, ricerche e configurazione dei tracker). Chiedere solo per spese, segreti e azioni irreversibili.
2. Se una cosa la puoi fare tu (Railway, tracker, URL, config), falla: non dare all'utente istruzioni da eseguire.
3. Ogni avviso deve poter dare margine >= 50 EUR e ROI >= 100%: pochi avvisi buoni, niente rumore (nemmeno nei gruppi Telegram).
4. Risposte in italiano: il risultato in una frase, poi dettagli brevi. Niente domande superflue.
5. Quando l'utente deve fare qualcosa: passi numerati, cosa cliccare e dove.
6. Niente AI o servizi a pagamento. Unica eccezione (4/10): la chiave Google dell'utente `GEMINI_API_KEY` come ultima riserva, distinta da `GEMINI_API_KEYS`, con tetto `PAGAMENTO_MAX_RICHIESTE_GIORNO`.
7. Niente API ne' scraping di vinted.it da parte di Claude: le pagine le scarica il bot (Claude puo' costruire URL, non visitarli).
8. Mai chiavi, password o token in file, commit, PR o chat; se compaiono nei log non riportarli; se l'utente ne incolla una, consigliare di ruotarla.
9. Non toccare `PROXY_LIST` / `PROXY_ESCLUSI` del worker. I proxy dei tracker (pagina /config) si copiano tra le istanze (consenso del 7/10).
10. Ricerche: `price_to` circa meta' della rivendita veloce; sotto 15 EUR (LEGO 25) niente.
11. Stime dichiarate come stime; i prezzi di rivendita si ricavano dai dati, non si inventano.
12. Banda proxy 250 GB al mese: dopo ogni cambio di volume controllare `RIEPILOGO BANDA` (`docs/procedure/consumi.md`).
13. Dopo ogni deploy verificare che moda e radar ricevano messaggi (`docs/procedure/controllo-deploy.md`).
14. Unire una PR solo con CI verde; se e' rossa anche su `main` (es. `ruff` del tracker), unire e dirlo.
15. Aggiornare `STATO.md` a ogni tappa chiusa.
16. Mai inventare dati: un numero che non si misura davvero non si stima e non si corregge; se un numero e' incerto, dire quanto e' sicuro (mai solo "dipende").
17. Prima di toccare qualcosa: pianificare e ragionare, niente tentativi improvvisati.
18. Termini tecnici con il nome vero e, tra parentesi, una spiegazione semplice.
19. Misurare sempre i tre obiettivi: semaforo vicino al Cervello e alla velocita' di vendita, falsi individuati, affari notificati in fretta.
20. Brand: Celine escluso, Missoni resta. Il banword `weekend` nel tracker esclude Weekend Max Mara di proposito.

Procedure fisse per i lavori ricorrenti (analisi log, ciclo modifica e merge, controllo deploy, variabili Railway, ricerche tracker, consumi, aggiornamento di `STATO.md`): `docs/procedure/`; recap mattutino: `docs/recap.md`.

## Pipeline
tracker (messaggio Telegram) -> `process_listing` (`bot/pipeline.py`) -> scrape pagina e foto -> stima rapida fair value (semaforo) -> Occhio (Gemini, vision) -> filtri pre-Cervello -> Cervello (JSON) -> `calcola_verdetto` (`bot/verdetto.py`, deterministico: il modello non calcola margine/ROI/decisione) -> messaggio Telegram.
- Meccanismi con soglie e variabili (fascia Gemini, semaforo, cascate e quote Gemini, riserva OmniRoute e a pagamento, risparmio, preavviso, scrape pagina leggera, pannello, tracciamento vendite, radar): **`docs/pipeline.md`**. Leggere la sezione che serve prima di toccare quel pezzo.

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
- Branch di lavoro `claude/...`, PR verso `main`, squash merge (`docs/procedure/ciclo-modifica.md`).

## Railway e dove guardare
- Progetto "Vinted Flip Oracle" `cd06f689-76ef-4b17-aee8-0c04dc03a4d9`, ambiente `6f828acc-20fc-4858-a48b-3f63f57a5a03`. Servizi: `worker` `7f856e1e-dad7-4798-90de-ac6ca77e5756`, `omniroute` `091a30ad-e994-4486-ab56-6f99b2b18521`.
- Progetto tracker "loyal-beauty" `6d89993f-2a71-4ff7-9746-83ed327195f9`, servizio `vinted-notifications` (ricerche: pagina `/queries`, modifica con POST a `/update_query/<id>`); secondo tracker `vinted-radar` `96bfce5d-2015-48a8-bfb1-7a62043907e3`.
- OmniRoute: dashboard con login; la password sta nelle variabili del servizio `omniroute`, non in questo file.
- Railway fa il deploy da `main` a ogni merge (circa 1,5 minuti). Variabili: `.env.example` (solo i nomi).

## Log
- Regole e filtri: `docs/log.md` e `docs/procedure/analisi-log.md`. In breve: filtri stretti e `limit` 20-40 per i controlli, `limit` 500 su file e `python3` per le analisi, mai righe incollate a mano.

## Convenzioni
- Codice e commenti in italiano, stile come quello vicino. Niente modifiche a `prompts.py` senza motivo: le calibrazioni per brand sono frutto di dati reali.
- Il pannello e la riserva usano `@c` in coda al modello per il prompt compatto; il suffisso non va mai al gateway. Niente push forzati su branch altrui.
