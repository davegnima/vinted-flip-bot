# Vinted Flip Oracle: guida per Claude

Userbot Telethon che riceve gli annunci dai tracker (`davegnima/Vinted-Notifications`), li valuta e manda l'avviso su Telegram. Due flussi: moda (tracker `vinted-notifications`) e radar fuori moda (tracker `vinted-radar`). Obiettivo: oggetti sottoprezzati (margine >= 50 EUR e ROI >= 100%), pochi falsi, cercando le eccezioni (venditori che prezzano male).

**A inizio sessione (o dopo una compattazione) leggere solo `STATO.md`** (stato corrente, controlli, punti aperti) e aggiornarlo a ogni tappa chiusa. Il resto si legge quando serve, secondo l'indice in fondo.

## Regole dell'utente (valgono sempre; le prime 3 contano di piu')
1. Non chiedere ok: fare e avvisare a cose fatte (codice, PR, merge, variabili Railway, servizi, ricerche e configurazione dei tracker). Chiedere solo per spese, segreti e azioni irreversibili.
2. Se una cosa la puoi fare tu (Railway, tracker, URL, config), falla: non dare all'utente istruzioni da eseguire.
3. Ogni avviso deve poter dare margine >= 50 EUR e ROI >= 100%: pochi avvisi buoni, niente rumore (nemmeno nei gruppi Telegram). Eccezione (8/11): nel radar un rosso per solo ROI tra 90% e 100% diventa giallo (`quasi_roi`, con suono dal 13/11) se margine >= 50 EUR, Jev dice affare con confidenza >= 0,85 e i comparabili sono >= 8 (`RADAR_QUASI_ROI_MIN`, 0 = spento).
4. Risposte in italiano: il risultato in una frase, poi dettagli brevi. Niente domande superflue.
5. Quando l'utente deve fare qualcosa: passi numerati, cosa cliccare e dove.
6. Niente AI o servizi a pagamento. Solo Gemini gratuito (cascate e chiavi di `GEMINI_API_KEYS`). OmniRoute, pannello di modelli, riserva e Serper sono stati tolti per scelta dell'utente: non reintrodurli. Unica eccezione: Jev (TypeSafe), budget impostato dall'utente in console, 20 EUR/mese dal 1/11. Nel radar niente Gemini per la stima, solo Jev; ai gialli e verdi che hanno gia' superato semaforo e Jev si aggiunge il controllo Gemini GRATUITO sulle foto (`bot/radar_gemini.py`, `RADAR_GEMINI`).
7. Niente API ne' scraping di vinted.it da parte di Claude: le pagine le scarica il bot (Claude puo' costruire URL, non visitarli).
8. Mai chiavi, password o token in file, commit, PR o chat; se compaiono nei log non riportarli; se l'utente ne incolla una, consigliare di ruotarla.
9. Non toccare `PROXY_LIST` / `PROXY_ESCLUSI` del worker. I proxy dei tracker (pagina /config) si copiano tra le istanze (consenso del 7/10).
10. Ricerche: `price_to` circa meta' della rivendita veloce, mai oltre 50 EUR (spesa massima per pezzo; radar: `RADAR_SPESA_MAX`); niente `price_from` (l'errore di prezzo a pochi euro e' l'affare; il rumore economico lo scarta il bot). Eccezioni: sul tracker `vinted-radar` le ricerche con lista modelli hanno `price_to` = buy max piu' alto della lista x 1,15 e il limite vero e' il buy max di ogni modello (18/10); nel radar non moda il tetto e' per categoria, 50 EUR di base e fino a 150 EUR per prodotti ad alto valore ovvio (console, utensili, hi-fi, foto; 31/10).
11. Stime dichiarate come stime; i prezzi di rivendita si ricavano dai dati, non si inventano.
12. Banda proxy 1 TB al mese (obiettivo di lavoro circa 30 GB/giorno): dopo ogni cambio di volume controllare `RIEPILOGO BANDA` (`docs/procedure/consumi.md`). Per l'utente il limite che conta sono le richieste a Vinted (rischio di blocco degli IP), non solo la banda.
13. Dopo ogni deploy verificare che moda e radar ricevano messaggi (`docs/procedure/controllo-deploy.md`).
14. Unire una PR solo con CI verde; se e' rossa anche su `main` (es. `ruff` del tracker), unire e dirlo.
15. Aggiornare `STATO.md` a ogni tappa chiusa (`docs/procedure/aggiorna-stato.md`): resta sotto le 60 righe, la cronologia va in `docs/storico/`.
16. Mai inventare dati: un numero che non si misura davvero non si stima e non si corregge; se un numero e' incerto, dire quanto e' sicuro (mai solo "dipende").
17. Prima di toccare qualcosa: pianificare e ragionare, niente tentativi improvvisati.
18. Termini tecnici con il nome vero e, tra parentesi, una spiegazione semplice.
19. Misurare sempre i tre obiettivi: semaforo vicino alla velocita' di vendita, falsi individuati, affari notificati in fretta.
20. Brand: Celine escluso, Missoni resta. Il banword `weekend` nel tracker esclude Weekend Max Mara di proposito.
21. Pokemon (carte, booster, ecc.) non si monitora mai: nessuna ricerca dedicata (7/11).

## Flussi
- **Moda**: tracker -> `process_listing` (`bot/pipeline.py`) -> scrape pagina e foto -> stima rapida (semaforo, `bot/fair_value.py`) -> `valuta_preavviso` -> avviso -> Jev sui comparabili (`bot/moda_jev.py`) -> Gemini gratuito sulle foto (`bot/moda_gemini.py`). Dal 1/11 `SOLO_SEMAFORO=1`: Occhio e Cervello (`occhio`, `verdetto`, `prompts`, `gemini_api`) sono spenti ma restano nel codice.
- **Radar**: tracker -> `bot/radar.py` -> filtro modelli (`radar_famiglie`) -> comparabili e semaforo (`radar_v2`, `valore_mercato`, `spedizione`) -> Jev (`jev`) -> Gemini gratuito sulle foto (`radar_gemini`) -> avviso; esiti nel DB (`archivio_radar`).
- Margine, ROI e decisione li calcola sempre Python, mai il modello.

## Mappa dei moduli (`bot/`)
- Config e utilita': `config`, `logger`, `costanti`, `testo`, `parsing`, `tempi`, `operazioni`.
- Logica pura: `schemas`, `prompts`, `occhio`, `verdetto`, `categorie`, `fair_value`, `velocita`, `filtri`, `comps_filtri`, `skip_report`, `valore_mercato`, `qualita_comps`, `spedizione`, `radar_famiglie`, `radar_matrice`.
- Stato e rete: `gemini_stato`, `proxy`, `http_clients`, `telegram_api`, `vinted_http`, `db`, `log_db`, `tracciamento`, `radar_appreso`, `archivio_radar`.
- Chiamate esterne: `gemini_api`, `vinted_scrape`, `vinted_search`, `vinted_api`, `foto`, `resellbot`, `comps`, `jev`.
- Flusso: `pipeline`, `scheda` (messaggi Telegram), `moda_jev`, `moda_gemini`, `feedback`, `radar`, `radar_v2`, `radar_gemini`.
- `main_telethon.py`: client Telethon, comandi, `main()` e un blocco di re-export (i test usano `m.NOME`).
- Direzione degli import: config/logger -> logica pura -> stato/client -> pipeline -> main. Niente import circolari (`tests/test_struttura.py` importa ogni modulo da solo).
- I client HTTP riassegnati a runtime si leggono come `hc._client_generico`, `hc._client_telegram`, `hc._CLIENT_VINTED_AUTH`: mai importarli per nome.

## Test, CI, convenzioni
- `python3 -m pytest -q` e `python3 -m pyflakes main_telethon.py bot` (la CI blocca solo i nomi non definiti), Python 3.13.
- Branch `claude/...`, PR verso `main`, squash merge. Railway fa il deploy da `main` a ogni merge (circa 1,5 minuti).
- Codice e commenti in italiano, stile come quello vicino. Niente modifiche a `prompts.py` senza motivo. Niente push forzati su branch altrui.

## Railway
- Worker: progetto "Vinted Flip Oracle" `cd06f689-76ef-4b17-aee8-0c04dc03a4d9`, ambiente `6f828acc-20fc-4858-a48b-3f63f57a5a03`, servizio `worker` `7f856e1e-dad7-4798-90de-ac6ca77e5756`.
- Tracker: progetto "loyal-beauty" `6d89993f-2a71-4ff7-9746-83ed327195f9`, servizi `vinted-notifications` (moda) e `vinted-radar` `96bfce5d-2015-48a8-bfb1-7a62043907e3`. Ricerche: pagina `/queries`, modifica con POST a `/update_query/<id>`.

## Quando leggere cosa (non leggere il resto)
| Devo... | Leggo |
|---|---|
| toccare un meccanismo, una soglia, una variabile | la sezione giusta di `docs/pipeline.md`; nomi delle variabili in `.env.example` |
| leggere o analizzare i log | `docs/log.md`, `docs/procedure/analisi-log.md` (`limit` 20-40 per i controlli, 500 su file e `python3` per le analisi, mai righe incollate a mano) |
| fare una modifica e unirla | `docs/procedure/ciclo-modifica.md`, poi `controllo-deploy.md` |
| cambiare una variabile Railway | `docs/procedure/variabili-railway.md` |
| cambiare le ricerche dei tracker | `docs/procedure/ricerche-tracker.md` |
| controllare banda e quote | `docs/procedure/consumi.md` |
| fare il recap mattutino | `docs/recap.md` |
| lavorare sulla matrice del radar | `docs/radar-matrice.md` |
| capire perche' una scelta e' stata fatta | `grep` in `docs/storico/` (mai leggerlo per intero) |
| riprendere il piano dell'audit | `docs/analisi/audit-2026-11-13.md` e `-task.md` |
