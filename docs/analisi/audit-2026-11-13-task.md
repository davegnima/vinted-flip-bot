# Task per l'esecutore (dall'audit del 13/11)

Contesto e numeri: `docs/analisi/audit-2026-11-13.md`. Regole: `CLAUDE.md`. Ogni task = una PR piccola (squash), `python3 -m pytest -q` e `python3 -m pyflakes main_telethon.py bot` senza "undefined name", CI verde, poi una voce in `docs/storico/` e `STATO.md` aggiornato (`docs/procedure/aggiorna-stato.md`).
Per la struttura usare Graphify (`graphify_find`, `graphify_callers`, `graphify_impact`, `graphify_tests_for`) prima di aprire i file. Mai leggere `docs/storico/` per intero.

Ordine consigliato: T1, T2, T7 (ondata 1) -> T3, T4, T5 (pulizia) -> T8, T9, T14, T15 (ondata 2) -> T6, T13 (struttura) -> T10, T16, T17 (ondata 3). T11 e' sul repo del tracker. T12 solo dopo conferma dell'utente.

| # | Titolo | Ondata | Dipende da | Modello |
|---|---|---|---|---|
| T1 | Esito finale del radar nel DB e campi mancanti nel tracciato | 1 | | Sonnet |
| T2 | Togliere 3 ricerche radar senza resa | 1 | | Haiku |
| T3 | `docs/pipeline.md` a sezioni e archivio dei documenti superati | pulizia | | Sonnet |
| T4 | Variabili d'ambiente: elenco completo e controllo automatico | pulizia | | Sonnet |
| T5 | Codice morto e re-export di `main_telethon.py` | pulizia | | Sonnet |
| T6 | Spezzare `main_telethon.py`, `scheda.py`, `radar.py` | struttura | T5 | Sonnet |
| T7 | Gemini del radar: meno "non disponibile" | 1 | | Sonnet |
| T8 | Jev: far passare `foto_diversa` come giallo muto (prova 7 giorni) | 2 | T1 | Sonnet |
| T9 | Test del percorso completo del radar | 2 | T1 | Sonnet |
| T10 | Misurare la sovrapposizione delle ricerche console | 3 | T1 | Haiku + Sonnet |
| T11 | Tracker: pulizia e `CLAUDE.md` | pulizia | | Sonnet |
| T12 | Archiviare il ramo Occhio/Cervello | struttura | conferma utente | Sonnet |
| T13 | Spezzare `pipeline.py`, `fair_value.py`, `verdetto.py` | struttura | T12 deciso | Sonnet |
| T14 | Seconda stima dai venduti veloci (ombra) | 2 | T1 | Sonnet |
| T15 | ROI sopra 300%: verde solo con 6 comparabili | 2 | | Sonnet |
| T16 | Tetti per modello misurati per le console nuove | 3 | T1 (7 giorni di dati) | Haiku + Sonnet |
| T17 | Una ricerca nuova alla volta: fotocamere compatte | 3 | T2, T10 | Sonnet |

---

## T1. Esito finale del radar nel DB e campi mancanti nel tracciato
- **File**: `bot/radar.py` (`invia_verdetto_v2`, dove si riempie `esito`), `bot/radar_v2.py` (`analizza`, `rivaluta`), `bot/archivio_radar.py` (`COLONNE`, `report_giornaliero`, `testo_report`), `bot/proxy.py` (contatore `RIEPILOGO BANDA`), `bot/tracciamento.py` (riga `TRACCIATO_RADAR`).
- **Cosa cambiare**
  1. Per ogni giallo o verde scrivere UN evento `radar_esito` (`db.scrivi_evento`) con: `item`, `ricerca`, `modello` (da `modello_famiglia`), `semaforo`, `esito` tra `inviato`, `scartato_jev`, `scartato_gemini`, `scartato_verifica`, `scartato_rivalutazione`, `jev_conf_bassa`, `errore_invio`, `altro`, e `motivo`. Nessun ritorno silenzioso: ogni `return` dopo il semaforo deve passare da qui.
  2. Aggiungere a `TRACCIATO_RADAR` e a `COLONNE`: `modello`, `titolo` (max 80 caratteri), `gemini` (esito e stima), `esito_finale`.
  3. `report_giornaliero`: colonne nuove `inviati` e `scartati` per ricerca; riga di controllo `REPORT RADAR | funnel | gv=N inviati=N scartati=N senza_esito=N`.
  4. `bot/proxy.py`: il tipo `pagina_annuncio` si divide in `pagina_annuncio` (primo scrape) e `pagina_ricontrollo` (chi chiama passa l'etichetta). Non toccare `PROXY_LIST` / `PROXY_ESCLUSI`.
- **Verifica**: test nuovo in `tests/test_archivio_radar.py` (la somma degli esiti e' uguale a gialli + verdi; `senza_esito` = 0 su un caso costruito per ogni ramo). In produzione dopo 24 h: `REPORT RADAR | funnel` con `senza_esito=0`.
- **Analisi gratuita da fare dopo 7 giorni** (Haiku, dal CSV `/esporta_radar`): venduti entro 1 h per `esito_finale`, per `modello`, per preferiti a 60 s (`pref_serie`), parole del titolo piu' frequenti tra i venduti entro 5 min.

## T2. Togliere 3 ricerche radar senza resa
- **Dove**: tracker `vinted-radar`, pagina `/queries` (procedura `docs/procedure/ricerche-tracker.md`).
- **Cosa**: salvare gli URL in `docs/analisi/radar-ricerche-potate-2026-11-14.json` e rimuovere `V2 vorwerk kobold`, `V2 shimano dura-ace`, `V2 campagnolo record` (0 gialli/verdi dal 9 al 13/11). Prima leggere `/queries` e riportare l'elenco vero delle ricerche attive in `STATO.md`.
- **Verifica**: `/queries` senza le tre voci; dopo 1 h nessuna riga `RADAR V2 OMBRA` con quelle ricerche.

## T3. `docs/pipeline.md` a sezioni e archivio dei documenti superati
- **File**: `docs/pipeline.md`, `docs/*.md`, `docs/analisi/*`.
- **Cosa cambiare**
  1. Riscrivere `docs/pipeline.md` con un indice in testa e una sezione `##` per meccanismo. Ogni sezione: 3-8 righe, tabella "variabile | default | cosa fa", file e funzione. Sezioni minime: stima rapida e semaforo, velocita', preavviso, Jev moda, Gemini moda, comparabili, scrape pagina, tracciamento vendite, cascate e quote Gemini, Telegram (blocchi e limitatore), radar: filtro modelli, radar: comparabili e semaforo, radar: Jev, radar: Gemini, radar: appreso, radar: spedizione, banda e contatori, pausa notturna. I default si leggono dal codice, non dalla vecchia versione.
  2. Togliere le frasi non piu' vere (radar "fermo dal 10/10", riserva, pannello) e marcare "spento (`SOLO_SEMAFORO=1`)" cio' che riguarda Occhio e Cervello, in una sezione in fondo.
  3. Spostare in `docs/archivio/` (con `git mv`, indice di una riga per file in `docs/archivio/README.md`): `proposta-radar-v2-2026-10-23.md`, `radar-recap-2026-10-23.md`, `brand-non-moda-2026-10-23.md`, `report_radar_31-10.md`, `motore-arbitraggio.md`, `prompt-prezzi-rivendita.md`, i file di `docs/analisi/` con data di ottobre e i `vestiaire_*`. Prima leggere le prime 5 righe di ciascuno: se e' citato dal codice (`grep -rn nomefile bot tools main_telethon.py`) resta dov'e'.
- **Verifica**: nessuna sezione sopra 1.500 caratteri; `grep -rn "docs/" CLAUDE.md STATO.md docs/procedure` non punta a file spostati; test verdi.

## T4. Variabili d'ambiente: elenco completo e controllo automatico
- **File**: `.env.example`, nuovo `tools/controlla_env.py`, nuovo `tests/test_env.py`.
- **Cosa cambiare**: lo script elenca i nomi letti con `os.environ.get`, `os.environ[...]`, `os.getenv` in `bot/` e `main_telethon.py` e li confronta con `.env.example`. Aggiungere a `.env.example` i 160 nomi mancanti, raggruppati per tema con il default del codice (solo nomi e default non segreti: mai valori di chiavi, token, proxy). Togliere `GEMINI_PAUSA_429_SECONDI`. Il test fallisce se una variabile letta non e' documentata o se una documentata non e' piu' letta.
- **Verifica**: `python3 tools/controlla_env.py` stampa 0 mancanti e 0 morte; test verde.

## T5. Codice morto e re-export di `main_telethon.py`
- **File**: `bot/moda_jev.py`, `bot/scheda.py`, `main_telethon.py`, `tests/`.
- **Cosa cambiare**
  1. Cancellare `_riga_dettagli_legit` (`bot/moda_jev.py:529`) e `_riga_semaforo_passo` (`bot/scheda.py:209`) dopo `graphify_callers` (devono avere 0 chiamanti).
  2. Le 7 funzioni usate solo dai test (elenco nell'audit, riga 13): per ciascuna decidere con `graphify_callers`: se nessun chiamante di produzione, cancellare funzione e test.
  3. Spostare il blocco di re-export di `main_telethon.py` (circa 460 righe) in `bot/esporta.py` e lasciare in `main_telethon.py` una riga `from bot.esporta import *` con `__all__` esplicito, cosi' `m.NOME` nei test continua a funzionare. Togliere gli import davvero inutili (`html`, `uuid`, `statistics`, `difflib`, `zlib` se pyflakes li conferma).
- **Verifica**: 504 test (meno quelli cancellati apposta) verdi; pyflakes su `main_telethon.py` sotto 20 avvisi; `tests/test_struttura.py` verde.

## T6. Spezzare `main_telethon.py`, `scheda.py`, `radar.py`
- **File**: `main_telethon.py` (1.751 righe), `bot/scheda.py` (980), `bot/radar.py` (935).
- **Cosa cambiare**: solo spostamenti, nessuna modifica di logica, una PR per file.
  - `main_telethon.py` -> `bot/comandi_radar.py` (`/report_radar`, `/esporta_radar`, ...), `bot/comandi_moda.py`, `bot/cicli.py` (cicli periodici, watchdog). In `main_telethon.py` restano client, registrazione dei gestori, `main()`.
  - `bot/scheda.py` -> `bot/scheda_testi.py` (funzioni pure che compongono il testo) e `bot/scheda_invio.py` (invio Telegram).
  - `bot/radar.py` -> `bot/radar_messaggi.py` (`testo_avviso_v2`, `testo_risposta_gruppo`, `compatta_didascalia`) e `bot/radar_invio.py` (`invia_verdetto_v2`, cancellazioni).
  - I vecchi moduli reimportano i nomi spostati (i test usano `m.NOME` e `bot.scheda.NOME`). Attenzione all'unico import pigro a rischio: `tracciamento -> radar` deve restare dentro la funzione.
- **Verifica**: `git diff --stat` mostra solo spostamenti; nessun file sopra 800 righe tra i tre; test e `tests/test_struttura.py` verdi; dopo il deploy `docs/procedure/controllo-deploy.md`.

## T7. Gemini del radar: meno "non disponibile"
- **File**: `bot/radar_gemini.py`, `bot/gemini_stato.py` (cascata della fase `occhio_radar`), `bot/radar.py` (punto in cui si invia senza Gemini).
- **Dato**: 12/11, 6 avvisi consegnati su 10 senza Gemini; 7 timeout `occhio_radar` su `gemini-3.1-flash-lite`, 3 pause da 120 s.
- **Cosa cambiare**: (1) per la fase `occhio_radar` mettere in testa alla cascata `gemini-3.5-flash-lite` (p50 4,0 s contro 3,6 s ma senza timeout nel campione: verificare prima con 24 h di `GEMINI_USO` filtrato su `occhio_radar`; se il campione non conferma, non cambiare l'ordine e dirlo); (2) se la fase e' in pausa al momento dell'avviso, inviare subito l'avviso (come oggi) e ritentare UNA volta a fine pausa aggiornando il messaggio; (3) riga di log `RADAR GEMINI | esito=ok|timeout|pausa|quota` per ogni giallo/verde.
- **Verifica**: test in `tests/test_radar_gemini.py` per il ritento; in produzione dopo 48 h quota di `Gemini: non disponibile` nelle righe `RADAR PRIVATO` sotto 2 su 10. Solo Gemini gratuito, nessun modello a pagamento.

## T8. Jev: far passare `foto_diversa` come giallo muto (prova 7 giorni)
- **File**: `bot/radar.py` (blocco `RADAR_JEV_RICHIESTO`, vicino a riga 340), `bot/jev.py` (`motivo_jev`).
- **Dato**: `foto_diversa` 23 venduti entro 1 h su 34 (68%); `ricambio` 2 su 19.
- **Cosa cambiare**: nuova variabile `RADAR_JEV_PASSA_MOTIVI` (default vuoto = comportamento di oggi). Se il motivo di Jev e' nell'elenco, l'avviso parte come giallo SENZA suono con la riga "Jev: foto diversa dai comparabili, controllare il modello". `ricambio`, `replica_dubbio`, `guasto_incompleto` restano bloccati. Impostare su Railway `RADAR_JEV_PASSA_MOTIVI=foto_diversa` (procedura `variabili-railway.md`).
- **Verifica**: test con la variabile vuota (nessun cambio) e con `foto_diversa`. Dopo 7 giorni e almeno 30 casi: venduti entro 1 h del gruppo. Sotto 45%: svuotare la variabile. Sopra 55%: lasciare e scriverlo in `STATO.md`.

## T9. Test del percorso completo del radar
- **File**: nuovo `tests/test_radar_percorso.py`.
- **Cosa**: con Jev, Gemini e Telegram finti, un caso per ramo: verde inviato; giallo `quasi_roi` ai tre confini (ROI 89,9 / 90; Jev 0,84 / 0,85; comparabili 7 / 8); scarto Jev sotto `RADAR_JEV_CONF_MIN`; scarto Gemini `stima_bassa`; `fuori_famiglia`; `sopra_tetto_modello`; `tetto_orario_nuovi`; spedizione `UNKNOWN` (tetto giallo). Ogni caso controlla anche l'evento `radar_esito` di T1.
- **Verifica**: test verdi; `graphify_tests_for bot/radar_v2.py` elenca il file nuovo.

## T10. Misurare la sovrapposizione delle ricerche console
- **Dato mancante**: non si sa quanti annunci di `V2 switch`, `V2 ps5`, `V2 3ds`, `V2 ps4 pro` arrivano anche da `V2 console` o `Console`.
- **Cosa** (Haiku, sola lettura): dai log del tracker `vinted-radar` (o dal CSV di T1 con `ricerca` e `item`) contare per 48 h gli item visti da piu' ricerche e, per ogni ricerca stretta, quanti item NON sono arrivati da `V2 console`. Ricordare `items_per_query=1`: una ricerca larga puo' perdere annunci tra due letture.
- **Decisione** (Sonnet): unire solo le ricerche strette i cui item arrivano da `V2 console` in almeno il 95% dei casi; le altre restano. URL vecchi salvati in `docs/analisi/`.
- **Verifica**: dopo l'unione, gialli+verdi al giorno delle console non sotto la media dei 5 giorni (155 validi in 5 giorni = 31 al giorno).

## T11. Tracker: pulizia e `CLAUDE.md` (repo `davegnima/Vinted-Notifications`)
- **File**: nuovo `CLAUDE.md` (massimo 30 righe: cosa fa, variabili proprie, come si cambiano le ricerche, rimando alle regole del repo del bot), `jev_test.py`, `jev_test/`, `vinted_notifications.py` (righe 235-237 e avvio di `rss_feed_process` a riga 211), `core.py` (`DEBUG_ORDINE_QUERIES`).
- **Cosa cambiare**: togliere il test Jev del 25/10 (`jev_test.py`, `jev_test/titoli.json`, ramo `JEV_TEST`); avviare il processo RSS solo se una variabile lo chiede (default spento, verificare prima su Railway che nessuno lo usi); lasciare `DEBUG_ORDINE_QUERIES` (spento di default) ma documentarlo. Sistemare gli errori `ruff` che rendono rossa la CI su `main`, senza cambiare logica.
- **Verifica**: `ruff check .` pulito; dopo il deploy dei due servizi righe `Scraped` nei log di `vinted-notifications` e `vinted-radar` e messaggi in arrivo al worker (`MESSAGGIO TRACKER`, `MESSAGGIO RADAR`). Non toccare i proxy.

## T12. Archiviare il ramo Occhio/Cervello (SOLO dopo conferma dell'utente)
- **Perche' serve conferma**: e' una scelta di prodotto (tornare al Cervello resterebbe possibile solo da git).
- **Cosa preparare prima di chiedere** (Haiku): eseguire i test con `coverage` e `SOLO_SEMAFORO=1`, elencare funzioni e righe mai eseguite in `bot/verdetto.py`, `bot/occhio.py`, `bot/skip_report.py`, `bot/prompts.py`, `bot/resellbot.py`, `bot/comps.py`, `bot/gemini_api.py`, `bot/schemas.py`, `bot/pipeline.py`; verificare su Railway che `SOLO_SEMAFORO=1`, `RESELLBOT_ATTIVO=0` e che le variabili `REDDIT_*` siano vuote.
- **Cosa cambiare se confermato**: spostare il ramo in `_archive/2026-11-cervello/` con i suoi test, togliere il ramo `if not SOLO_SEMAFORO` da `bot/pipeline.py`, tenere `calcola_verdetto` solo se usato da moda Jev o radar (`graphify_callers`).
- **Verifica**: test verdi, righe di `bot/` scese del numero misurato, moda e radar ricevono messaggi dopo il deploy.

## T13. Spezzare `pipeline.py`, `fair_value.py`, `verdetto.py`
- **Dipende** dalla decisione di T12 (se il ramo Cervello va in archivio, `verdetto.py` e meta' di `pipeline.py` spariscono e non vanno spezzati).
- **Cosa cambiare** (solo spostamenti): `_process_listing_interno` (868 righe) in passi con nome: `_passo_scrape`, `_passo_stima`, `_passo_preavviso`, `_passo_jev`, `_passo_gemini`, ognuno una funzione che riceve e restituisce un contesto; `bot/fair_value.py` -> `bot/fair_value_tabelle.py` (dati e tarature) + `bot/fair_value.py` (calcolo) + `bot/preavviso.py` (`valuta_preavviso`).
- **Verifica**: nessuna funzione sopra 150 righe nei file toccati; `tests/test_preavviso.py`, `tests/test_verdetto_e_stima.py`, `tests/test_struttura.py` verdi senza modifiche ai test (solo import).

## T14. Seconda stima dai venduti veloci (ombra)
- **File**: nuovo `bot/radar_veloci.py`, `bot/radar_v2.py` (`analizza`, solo log), `bot/archivio_radar.py`.
- **Cosa cambiare**: dal DB (`tracciato_radar`, ultimi 30 giorni) costruire per famiglia normalizzata (`radar_appreso.normalizza`) la mediana dei prezzi degli annunci venduti entro 1 h (minimo 5 casi). In `analizza` calcolare `riv_veloci` e `margine_veloci` e scriverli nell'evento e nella riga `RADAR V2 OMBRA`. NON cambia il semaforo. Nessuna richiesta a Vinted.
- **Verifica**: test su funzioni pure. Dopo 7 giorni (Haiku, dal CSV): quanti rossi `margine_basso` avrebbero margine >= 50 con `riv_veloci` e quanti di loro hanno venduto entro 1 h. Se sono almeno 30 e vendono sopra il 55%, proporre all'utente di usarla per il giallo.

## T15. ROI sopra 300%: verde solo con 6 comparabili
- **File**: `bot/radar_v2.py` (dove si decide verde/giallo), `bot/valore_mercato.py` (`semaforo`).
- **Dato**: ROI > 300% vende 46% (44 su 96), ROI < 150% vende 60% (48 su 80).
- **Cosa cambiare**: variabile `RADAR_ROI_SOSPETTO` (default 300, 0 = spento): sopra quel ROI il verde richiede `n >= 6` comparabili dello stesso modello, altrimenti giallo con motivo `roi_sospetto`.
- **Verifica**: test ai confini; dopo 7 giorni venduti entro 1 h dei `roi_sospetto` confrontati con i verdi.

## T16. Tetti per modello misurati per le console nuove
- **File**: `bot/radar_famiglie.py`.
- **Cosa** (Haiku poi Sonnet): dopo 7 giorni di dati con il campo `modello` (T1), per ps4, ps vita, wii u, game boy, psp, ds: gialli+verdi validi e venduti entro 1 h per fascia di prezzo (sotto 25, 25-50, 50-80, 80-150). Alzare il tetto di un modello solo se la fascia sopra il tetto attuale non e' misurabile (allora provare +30 EUR per 7 giorni) o se la fascia alta vende sopra il 55% con almeno 10 casi; togliere dalla lista i modelli con 0 gialli/verdi su almeno 30 valutazioni.
- **Verifica**: tabella nello storico radar; rifiuti 403/429 del giorno prima e dopo.

## T17. Una ricerca nuova alla volta: fotocamere compatte
- **Dove**: tracker `vinted-radar` e `tools/radar_liste/v2_ricerche.py`.
- **Cosa**: una sola ricerca `V2 compatte digitali`: marche Canon, Sony, Nikon, Olympus (id in `tools/radar_liste/dati/brand_ids.json`), catalogo delle fotocamere compatte letto dal campo `catalogo=` dei log degli annunci gia' visti (non inventare l'id, non visitare Vinted), `price_to` 50, niente `price_from`. Mai Pokemon. Partire solo dopo T2 (tre ricerche in meno) cosi' le richieste del tracker non salgono.
- **Misura di successo** (7 giorni): almeno 10 gialli/verdi validi e almeno il 50% venduti entro 1 h.
- **Criterio di spegnimento**: 0 gialli/verdi in 7 giorni, oppure sotto il 40% con almeno 15 casi, oppure rifiuti su `pagina_annuncio` sopra il 5% nel giorno.
