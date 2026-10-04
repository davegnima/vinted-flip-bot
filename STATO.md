# Stato del progetto (aggiornato 2026-10-04)

Da rileggere all'inizio di ogni sessione nuova, dopo `CLAUDE.md`. Aggiornare a ogni tappa chiusa.

## Fatto e in produzione (main)
- Messaggio compatto per tutte le decisioni; SKIP non manda messaggi (resta il log `SKIP non inviato`).
- Riserva a scalata via OmniRoute (`bot/riserva_llm.py`), spenta finche' `RISERVA_*` e' vuota.
- Pannello in ombra ridotto (vedi sotto). `CLAUDE.md` con regola dei filtri larghi sui log (#59).
- Log `MESSAGGIO TRACKER` / `MESSAGGIO SCARTATO` per i messaggi del tracker senza traccia (#60).
- Preavviso (#61): la scheda anticipata diventa push con suono se `valuta_preavviso` scatta (🟢 con margine >= 25 EUR, oppure prezzo <= 25 EUR con margine >= 20 EUR). Soglie `PREAVVISO_*`, spento con `PREAVVISO_ATTIVO=0`. Una riga `PREAVVISO |` per annuncio.
- Icona `⚠️ dati deboli` per COMPRA/TRATTA con stima instabile o un solo comp.
- Nota "senza strumenti" per pannello e riserva (Groq dava 400 per `cerca_comp_prezzo`).

- Archivio per annuncio (PR archivio-annunci): la riga `PREAVVISO` ora ha categoria, condizione, materiale, taglia, lingua del titolo, n. foto, dati venditore, ora/giorno; evento `annuncio` nel DB; `ESITO` ha `item=`. Serve all'apprendimento dalla velocita' di rotazione (etichetta = classe di vendita, non il feedback dell'utente).
- Recap mattutino spostato alle 05:47 (ora italiana) con sezione apprendimento dalla rotazione e indice di sostituibilita' del Cervello.

- Semaforo totale (PR semaforo-totale): ogni annuncio con brand ha un semaforo; categoria anche da catalogo Vinted (mappa autoappresa su /data/catalogo_categorie.json, semi 532 e 1786 = giacca); brand nuovi Prada/Fendi/Jacquemus/Acne/Barena a confidenza bassa; taratura x1,20 (Missoni prima linea +10%, Cucinelli +15%, in piu' della taratura); stime a confidenza bassa con soglie x1,5 e fascia Gemini scelta dal prezzo; preavviso solo con confidenza non bassa. Replay sugli 87 annunci di ieri (in-sample, senza tabella appresa): verde 57% vendite rapide, giallo 36%, rosso 16%. Da verificare nel recap: quota di verdi, annunci in fascia alta Gemini al giorno (replay: 52 su 87 contro 46), preavvisi al giorno (replay: 24 su 87) e quanti vendono veloci; le voci apprese non ricevono la taratura e fv_ricalibra parte dal valore di tabella non tarato (puo' far scendere il valore).

- Preferiti (verificato nei log il 4/10: il campo c'e', valori 0-1 sui nuovi annunci; le visualizzazioni non si leggono dalla pagina e sono state tolte): `preferiti=` in `RICONTROLLO LAMPO`, `pref=` in `PREAVVISO`. Al recap controllare la crescita dei preferiti tra 15 s, 30 s, 60 s, 5 min come predittore di AFFARE/MEDIO e possibile segnale per semaforo e preavviso. `PREAVVISO` ha anche `fonte_cat`.

## Variabili Railway del worker (non in repo)
- `PANEL_CERVELLO_MODELLI=mistral/ministral-14b-2512@c,zai/glm-4.7-flash@c,nvidia/nvidia/nemotron-3-super-120b-a12b@c,groq/openai/gpt-oss-120b@c,groq/openai/gpt-oss-20b@c`
- `PANEL_OCCHIO_MODELLI=mistral/ministral-14b-2512`; `PANEL_MODELLI_PER_ANNUNCIO=8`; `GEMINI_SOGLIA_PREZZO_ALTO=50`; `RESELLBOT_ATTIVO=0`; `RISERVA_*` non impostate.
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
- Il recap mattutino (routine 07:42 Europe/Rome) arriva in questa sessione.
