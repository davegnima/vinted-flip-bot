# Stato del progetto (aggiornato 2026-11-13)

Da rileggere a inizio sessione dopo `CLAUDE.md`. Solo stato corrente, controlli e punti aperti: massimo 60 righe.
La cronologia NON sta qui: `docs/storico/` (indice in `docs/storico/README.md`). Regole per aggiornare: `docs/procedure/aggiorna-stato.md`.

## Stato corrente

**Moda** (tracker `vinted-notifications`)
- Dal 1/11 Occhio e Cervello erano spenti (`SOLO_SEMAFORO=1`); il 13/11 sono stati tolti dal codice (`_archive/2026-11-cervello/README.md`). L'avviso parte dalla stima rapida (`valuta_preavviso`), poi Jev cerca i comparabili (`bot/moda_jev.py`) e Gemini gratuito guarda le foto (`bot/moda_gemini.py`).
- Soglie in uso: margine rapido minimo 40 EUR per avvisare (`PREAVVISO_MARGINE_ASSOLUTO_MIN`), Jev scarta sotto 40 EUR di margine (`MODA_JEV_MARGINE_MIN`), tetto verifiche Jev `MODA_JEV_MAX_GIORNO`=1500 su Railway (alzato il 12/11 da 600), ombra 20/h fuori dal tetto.
- Comparabili: una sola richiesta con condizioni 1+2+3 (scelta dell'utente dell'11/11), rivendita mista con pesi scelti dall'utente (non misurati).
- Ricerche: ultime potature 11-13/11 (Versace, Belstaff, Acne, Frankie Shop, Stella McCartney, Farm Rio, Etro, Balmain, McQueen, Chloe; Barbour solo fino a 20 EUR nella ricerca 27). Elenco vero: pagina `/queries` del tracker.
- Ultimo recap (dati 12/11): veloci 15,8%; semaforo verde 37%, giallo 16%, rosso 9%; preavviso precisione 26%, richiamo 64%.

**Radar fuori moda** (tracker `vinted-radar`)
- Ricerche attive: circa 17 (19 il 9/11, tolte `V2 ghd` e `V2 audio e hifi` il 13/11); numero da confermare su `/queries`.
- Valutazione: `bot/radar_v2.py` (comparabili Vinted, 25° percentile), filtro modelli `bot/radar_famiglie.py` (tetti: ps5 150, switch 90, ps4/ps vita/wii u 80, ps4 pro/3ds 60, altri 50), Jev richiesto con confidenza >= 0,7, Gemini gratuito sulle foto, eccezione `quasi_roi`.
- Avvisi: gialli e verdi con suono (13/11), rossi cancellati dal gruppo.
- Numeri misurati 9-13/11 (774 annunci tracciati): venduti entro 1 h verdi 68%, gialli 49%, rossi 29%. Il 12/11 (08-20 UTC): 73 gialli/verdi, 10 avvisi consegnati. Dettaglio: `docs/analisi/audit-2026-11-13.md`.

**Infrastruttura**
- Banda proxy del worker misurata: 4,4 GB l'11/11, 3,4 GB il 12/11 (obiettivo 30 GB/giorno, tetto 1 TB/mese): ampio margine. Rifiuti 403/429 su `pagina_annuncio`: 2,1% l'11/11, 1,7% il 12/11, 4,0% il 13/11 (fino alle 16:31 UTC).
- Contatori e log salvati in SQLite sul volume `/data` (`bot/db.py`, `bot/log_db.py`); niente Postgres.
- Telegram: il blocco 429 si rispetta sempre; i messaggi con suono non passano dal limitatore.
- Tracker: `items_per_query=1` (deciso dall'utente, non cambiare).
- Il recap mattutino (routine 05:47 Europe/Rome) arriva nella sessione: istruzioni in `docs/recap.md`.

## Controlli da fare
1. Barbour a 20 EUR (ricerca 27): veloci % e volume dopo qualche giorno.
2. Tetto Jev 1500: verifiche al giorno e righe `tetto_giornaliero` (devono restare 0).
3. Margini dei COMPRA sotto 40 EUR (Missoni, Amiri, Max Mara, Balmain...) contro `PREAVVISO_MARGINE_ASSOLUTO_MIN`.
4. Ombra moda: quante coppie brand|categoria arrivano a 5 campioni (`MODA JEV OMBRA`, campo `campioni`).
5. Radar: Gemini "non disponibile" in 6 avvisi su 10 il 12/11; `Gemini TIMEOUT` ogni giorno (29 in 6 ore il 12/11, 21 su `gemini-3.1-flash-lite`).
6. Radar: tabella per modello delle famiglie nuove (ps4, ps vita, wii u, game boy, psp, ds) e rifiuti 403/429; se salgono, abbassare `RADAR_FAMIGLIE_NUOVE_ORA`.
7. Radar: una ricerca senza gialli/verdi in 7 giorni si toglie (`/report_radar`, `/esporta_radar`).
8. Dopo il 13/11: `REPORT RADAR | funnel` con `senza_esito=0`; `profilo_venditore` fermo nel `RIEPILOGO BANDA OGGI`; tempi `GEMINI_USO` della moda con il prompt nuovo; avvisi moda e radar regolari dopo la rimozione di Occhio e Cervello.

## Punti aperti
- **Audit del 13/11**: `docs/analisi/audit-2026-11-13.md` e `-task.md`. Fatti il 13/11: domanda foto di Jev tolta (#406), funnel del radar nel DB (T1, #407), prompt Gemini moda con le regole di Occhio e Cervello (#408), ramo Occhio/Cervello tolto (T12, #409), codice morto e scrape del guardaroba tolti (T5, #410), variabili e `docs/pipeline.md` (T3, T4), pulizia del tracker (T11, tracker #37). Codice da 20.870 a 13.619 righe.
- Restano dall'audit: T2 (togliere `V2 vorwerk kobold`, `V2 shimano dura-ace`, `V2 campagnolo record`), T6 (spezzare `main_telethon.py`, `radar.py`, `fair_value.py`), T7 (Gemini del radar "non disponibile"), T9 (test del percorso radar), T14, T15. Ondata 3 (nuove ricerche) ferma per scelta dell'utente.
- `MODA_JEV` ha default diversi nel codice (0 in `bot/moda_jev.py`, 1 in `bot/fair_value.py`): in produzione e' impostata, ma va unificata.
- Tracker: `ruff` resta rosso (87 errori che richiedono cambi di comportamento); le PR del tracker non fanno partire la CI.
- Per l'utente: ruotare le chiavi incollate in chat in passato (Z.ai, token Graphify, Groq, OmniRoute).

## Dove guardare (un puntatore per tema)
| Tema | File |
|---|---|
| Meccanismi, soglie e variabili | `docs/pipeline.md` |
| Log: parole esatte e filtri | `docs/log.md`, `docs/procedure/analisi-log.md` |
| Lavori ricorrenti | `docs/procedure/README.md` |
| Recap mattutino | `docs/recap.md` |
| Matrice modelli del radar | `docs/radar-matrice.md`, `data/radar_matrice.json` |
| Ricerche tolte (URL per rimetterle) | `docs/analisi/radar-ricerche-potate-*.json`, `docs/analisi/moda-*` |
| Cronologia e motivi delle scelte | `docs/storico/README.md` |
