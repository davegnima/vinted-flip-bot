# Stato del progetto (aggiornato 2026-10-07)

Da rileggere all'inizio di ogni sessione nuova, dopo `CLAUDE.md`. Aggiornare a ogni tappa chiusa.

## Fatto e in produzione
Cronologia completa in `docs/storico.md`. Sintesi: pipeline moda con semaforo, preavviso, riserva OmniRoute (+ chiave a pagamento, oggi 401 da rigenerare), tracciamento vendite fino a 1 h, radar fuori moda fase 0 con secondo tracker `vinted-radar`.

- 7/10 riordino documenti: `CLAUDE.md` snello (48 righe), dettagli in `docs/pipeline.md` e `docs/log.md`, cronologia in `docs/storico.md`, `.env.example` aggiornato (solo nomi), `DEPLOY_RAILWAY.md` (obsoleto, guida alla prima installazione) archiviato in `_archive/2026-10-07/`.

## Variabili Railway del worker (non in repo)
- `PANEL_CERVELLO_MODELLI=mistral/ministral-14b-2512@c,zai/glm-4.7-flash@c,nvidia/nvidia/nemotron-3-super-120b-a12b@c,groq/openai/gpt-oss-120b@c,groq/openai/gpt-oss-20b@c`
- `PANEL_OCCHIO_MODELLI=mistral/ministral-14b-2512`; `PANEL_MODELLI_PER_ANNUNCIO=8`; `GEMINI_SOGLIA_PREZZO_ALTO=50`; `RESELLBOT_ATTIVO=0`; `RISERVA_OCCHIO_MODELLI` e `RISERVA_CERVELLO_MODELLI` impostate il 4/10.
- Tracker: `items_per_query=1` (deciso dall'utente, non cambiare).

## Da controllare (prossima sessione)
1. Dopo il deploy: righe `PREAVVISO |` e `MESSAGGIO TRACKER`; contare quanti push al giorno farebbe `regola=semaforo|prezzo_basso` e incrociarli con `RICONTROLLO LAMPO` (precisione sui venduti entro 30 s). Tarare `PREAVVISO_*`.
2. Errori `PANEL HTTP` di Groq (400 dovrebbe sparire), GLM-4.7-flash (429 a 1 richiesta/s), Nemotron-3-super; togliere dal pannello chi non e' recuperabile.
3. I 13 NON COMPRARE venduti in fretta: 7 su 13 "sospetto"; Max Mara 35 EUR con target dichiarato 100 e margine 5 (limite sul target?). Cercare un pattern con le righe `PREAVVISO`.
4. I 4 messaggi del tracker senza traccia nel worker (02:07 id 10234437172, 02:35 id 10234517354, 05:08, 05:10): usare i nuovi log per capire la causa.
5. Primo blazer reale (Max Mara / uomo) dalla ricerca 2 del tracker.
6. Dati deboli: 25% di COMPRA/TRATTA con stima instabile, 15 COMPRA con un solo comp: verificare se vendono piu' lentamente.

## Aperti per l'utente
- Ruotare le chiavi incollate in chat: Z.ai, token Graphify, Groq, chiave OmniRoute.
- Mistral Large risponde 403 sull'account: controllare la console Mistral.
- Tracker: nessuna modifica in corso.

## Regole di lavoro apprese
- Niente AI a pagamento; niente API/scraping Vinted da parte di Claude; non toccare `PROXY_LIST` / `PROXY_ESCLUSI`.
- Log: sempre filtri stretti e `limit` basso; per analisi su ore salvare su file e usare Python.
- Il recap mattutino (routine 05:47 Europe/Rome) arriva in questa sessione.
