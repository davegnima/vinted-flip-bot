# Stato del progetto (aggiornato 2026-10-07)

Da rileggere all'inizio di ogni sessione nuova, dopo `CLAUDE.md`. Aggiornare a ogni tappa chiusa.

## Fatto e in produzione
Cronologia completa in `docs/storico.md`. Sintesi: pipeline moda con semaforo, preavviso, riserva OmniRoute (+ chiave a pagamento, oggi 401 da rigenerare), tracciamento vendite fino a 1 h, radar fuori moda fase 0 con secondo tracker `vinted-radar`.

- 7/10 riordino documenti: `CLAUDE.md` snello (48 righe), dettagli in `docs/pipeline.md` e `docs/log.md`, cronologia in `docs/storico.md`, `docs/recap.md` (istruzioni del recap, lette dalla routine delle 05:47), `.env.example` aggiornato (solo nomi), `DEPLOY_RAILWAY.md` (obsoleto, guida alla prima installazione) archiviato in `_archive/2026-10-07/`.

- 7/10 16:25 UTC, dati prime 3h20 (957 promossi su ~1250; ~20 GB/giorno di proxy, ridotti con #88): vendite rapide quasi solo LEGO (Star Wars/Technic con numero di set, alcuni venduti prima della prima lettura) e oggetti economici (Alessi 8-20 EUR, minifigure). Audio, libri, Contax, argento quasi senza annunci. Ricerche riscritte (rumore): LEGO star wars / technic / ideas / sigillato con catalogo 1767 + brand 89162, 25-80 EUR; game boy / gamecube / nintendo 64 con catalogo 3026 (il brand Nintendo nei videogiochi restituisce solo annunci vecchi: tolto), 15-40/50; artemide / flos / fontana arte / oluce / kartell con cataloghi lampade 3836, 3862, 3839; bitossi / fornasetti con 1960, 1940; persol brand 12775 + cataloghi 98, 26; oliver peoples con 98, 26; vitra, bang olufsen, contax, georg jensen solo testo; tolti alessi, audeze, lampada vintage. Prezzo minimo 15 EUR (LEGO 25). Da verificare l'8/10: banda, promossi/ora, vendite rapide per ricerca.
- 7/10 sera: pausa notturna del radar nel worker (23-6 ora italiana, `RADAR_PAUSA_DA/A`): niente visite ne' ricontrolli, ma il tracker `vinted-radar` continua a leggere Vinted e a consumare proxy di notte (il suo `/control/telegram/stop` ferma solo l'invio, non lo scraper; fermarlo del tutto richiede di fermare il servizio su Railway o cambiare `query_refresh_delay`, che sta nel form di `/config` insieme al token).

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
