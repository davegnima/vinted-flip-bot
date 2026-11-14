# Pipeline e meccanismi

Un meccanismo per sezione. I default sono quelli letti dal codice il 13/11; l'elenco completo delle variabili e' in `.env.example` (controllato da `tools/controlla_env.py` e `tests/test_env.py`). La cronologia delle scelte e' in `docs/storico/`.

Flusso moda: tracker -> `process_listing` (`bot/pipeline.py`) -> filtri -> scrape pagina e foto -> stima rapida e semaforo -> `valuta_preavviso` -> avviso -> Jev -> Gemini. Flusso radar: tracker -> `bot/radar.py` -> filtro modelli -> comparabili e semaforo -> Jev -> Gemini -> avviso.

## Indice
- Moda: [stima rapida e semaforo](#stima-rapida-e-semaforo) · [velocita](#velocita) · [preavviso](#preavviso) · [Jev moda](#jev-moda) · [Gemini moda](#gemini-moda) · [comparabili](#comparabili) · [scrape pagina](#scrape-pagina)
- Comuni: [tracciamento vendite](#tracciamento-vendite) · [cascate e quote Gemini](#cascate-e-quote-gemini) · [Telegram](#telegram-blocchi-e-limitatore) · [banda e contatori](#banda-e-contatori) · [pausa notturna](#pausa-notturna) · [arresto e watchdog](#arresto-e-watchdog)
- Radar: [filtro modelli](#radar-filtro-modelli) · [comparabili e semaforo](#radar-comparabili-e-semaforo) · [Jev](#radar-jev) · [Gemini](#radar-gemini) · [appreso](#radar-appreso) · [spedizione](#radar-spedizione)
- [Ramo Occhio e Cervello](#ramo-occhio-e-cervello-rimosso)

## Stima rapida e semaforo
`stima_fair_value` (`bot/fair_value.py`): ogni annuncio con brand ha un fair value (rivendita stimata) e un semaforo. Ordine: tabella dati, appreso dai verdetti (`fv_carica_appreso`), livello del brand x fattore categoria, livello di default. La categoria viene da titolo, descrizione o catalogo Vinted.

| variabile | default | cosa fa |
|---|---|---|
| FAIR_VALUE_ROI_VERDE / _GIALLO | 200 / 100 | ROI minimo (%) di verde e giallo |
| FAIR_VALUE_MARGINE_MIN_VERDE | 20 | margine minimo (EUR) del verde |
| FAIR_VALUE_LIVELLO_DEFAULT | 45 | rivendita se il brand e' ignoto |
| FAIR_VALUE_TARATURA_GLOBALE | 1.20 | fattore sulle voci non apprese |
| FAIR_VALUE_TARATURA_BRAND | missoni=1.10,brunello cucinelli=1.26,prada=1.30 | fattori per brand |
| FAIR_VALUE_RIGORE_BASSA | 1.0 | moltiplicatore soglie a confidenza bassa |
| FAIR_VALUE_FILTRA / _FILTRA_ROI_MIN | 0 / 30 | scarto anticipato per ROI basso |

## Velocita
`bot/velocita.py` (`lift_brand`, `semaforo_corretto`): il semaforo si moltiplica per il lift del brand (quota di vendite entro 15 min, ristretta verso la media). Soglie proporzionali alla media della tabella `bot/dati/velocita.json`; la copia aggiornata sta sul volume e si rigenera con `tools/aggiorna_velocita.py`.

| variabile | default | cosa fa |
|---|---|---|
| VELOCITA_ATTIVA | 1 | 0 spegne la correzione |
| VELOCITA_K | 10 | peso della restrizione verso la media |
| VELOCITA_VERDE_X / _GIALLO_X | 1.6 / 0.8 | soglie in multipli della media |
| VELOCITA_SOGLIA_VERDE / _GIALLO | vuoto (0) | soglie fisse, 0 = proporzionali |
| VELOCITA_PREZZO_NEUTRO | 20 | sotto questo prezzo il lift lento non agisce |
| VELOCITA_SOLO_ROSSO | 1 | il lift basso agisce solo sui rossi |

## Preavviso
`valuta_preavviso` (`bot/fair_value.py`, testo in `bot/scheda.py::testo_preavviso`): se la stima rapida e' promettente un album con il semaforo parte nel gruppo COMPRA (`TELEGRAM_ALERT_CHAT_ID`) e a fine analisi lo stesso messaggio si aggiorna col verdetto. Il lampo parte prima dello scrape con la foto del tracker. Se l'annuncio e' scartato, resta un messaggio compatto con il motivo.

| variabile | default | cosa fa |
|---|---|---|
| PREAVVISO_ATTIVO / _LAMPO | 1 / 1 | interruttori del preavviso e del lampo |
| PREAVVISO_MARGINE_MIN / _BASSO / _NUOVI | 25 / 20 / 50 | margini minimi (EUR) |
| PREAVVISO_PREZZO_BASSO | 20 | sotto questo prezzo vale il margine basso |
| PREAVVISO_GIALLO_PREZZO_MAX | 15 | ogni giallo fino a qui manda e suona |
| PREAVVISO_SUONO_MARGINE_MIN / _ROI_MIN | 40 / 100 | ogni preavviso con margine rapido e ROI sopra queste soglie suona, di qualunque colore (14/11) |
| PREAVVISO_SUONO_RAPPORTO_MIN / _VERDE | 4 / 1 | regole del suono |
| PREAVVISO_BRAND_ESCLUSI / _FACILI | acne studios,marni,lancel / jean paul gaultier | liste brand |
| PREAVVISO_DA_VERIFICARE(_MARGINE) | 1 (50) | avviso "da verificare" |

## Jev moda
`bot/moda_jev.py`: Jev (TypeSafe, a budget) giudica comparabili e autenticita'; l'avviso parte subito e si aggiorna con l'esito. `correggi_per_difetti` abbassa la rivendita; `rivendita_mista` pesa semaforo, comparabili e Gemini (pesi: regola pratica, non misurata). Margine, ROI ed esito li calcola Python.

| variabile | default | cosa fa |
|---|---|---|
| MODA_JEV | 0 in `moda_jev.py`, 1 in `fair_value.py` | interruttore: in produzione si imposta a 1 |
| MODA_JEV_SUBITO | 1 | avviso subito, poi aggiornato |
| MODA_JEV_TUTTI | 0 | 1 = verifica anche i brand non nuovi |
| MODA_JEV_MAX_GIORNO | 600 | verifiche massime al giorno |
| MODA_JEV_MARGINE_MIN | 40 | sotto questo margine (EUR) scarta |
| MODA_JEV_DISPERSIONE_MAX | 2.5 | p75/p25 dei comparabili, 0 = spento |
| MODA_JEV_OMBRA / _MAX_ORA | 1 / 20 | prova in ombra e suo tetto orario |
| PREAVVISO_TUTTI_A_JEV | 1 | tutti gli avvisi vanno a Jev |

## Gemini moda
`bot/moda_gemini.py::controlla`: una chiamata gratuita sulle foto legge autenticita', capo, condizione, difetti (gravita' con sconto massimo lieve 15%, moderata 35%, grave 60%), tipo oggetto (`non_moda` con confidenza >= 0,7 scarta) e consiglio. La sua stima di rivendita entra nella media mista. Prompt in `bot/prompt_moda.py`.

| variabile | default | cosa fa |
|---|---|---|
| MODA_GEMINI | 1 | 0 spegne il controllo |
| MODA_GEMINI_SEMPRE | 1 | su ogni avviso, non solo se Jev dubita |
| MODA_GEMINI_MAX_ORA | 60 | chiamate massime all'ora |
| MODA_GEMINI_FOTO | 8 | foto massime per chiamata |
| MODA_GEMINI_REGOLE_PREZZO | 1 | regole di prezzo nel prompt |

## Comparabili
`bot/vinted_search.py` e `bot/comps.py`: ricerca dei prezzi in vendita dello stesso articolo; `bot/valore_mercato.py` (`stima_mercato`, `comparabili_simili`) toglie i fuori scala e calcola la stima, `bot/qualita_comps.py` e `bot/comps_filtri.py` filtrano. La condizione corregge i prezzi con una scala.

| variabile | default | cosa fa |
|---|---|---|
| COMPS_COND_SCALA | 1 | moltiplicatore della correzione per condizione, 0 = nessuna |
| MODA_COMPS_ORDINE | newest_first | ordine dei comparabili cercati |
| MODA_COMPS_PROVA | vuoto | ordini alternativi da provare |
| VINTED_API | 1 | 0 = solo scraping HTML |

## Scrape pagina
`scrape_vinted_listing` (`bot/vinted_scrape.py`): scarica la pagina dell'annuncio con un proxy. Se la risposta e' 200 ma leggera (Vinted serve ai bot una pagina senza foto) riprova con un altro proxy e logga `Pagina annuncio leggera`. Le foto si scaricano in `bot/foto.py`.

| variabile | default | cosa fa |
|---|---|---|
| PAGINA_LEGGERA_MAX_CARATTERI | 60000 | sotto questa lunghezza la pagina e' leggera |
| PAGINA_LEGGERA_RETRY | 2 | ritentativi con un altro proxy |
| FOTO_DIRETTE | 1 | 0 spegne lo scarico diretto delle foto |
| VINTED_ATTESA_403_S | 1 | attesa (s) dopo un 403 |
| LAMPO_SENZA_CATEGORIA_MARGINE_MIN | 50 | margine (EUR) del lampo senza categoria |

## Tracciamento vendite
`bot/tracciamento.py` (`tracc_avvia_serie`, `_tracc_serie_interna`, `tracc_riprendi_serie`): ricontrolli a 15 s, 30 s, 1, 5, 15 min, 1 h; serie ridotta (5, 15 min, 1 h) per gli scartati. Una riga `TRACCIATO` a fine serie con esito del bot e di vendita; le serie pendenti stanno nel DB e si riprendono all'avvio. `rimosso?` = pagina 200 senza dati; `prenotato` entro 1 h vale come venduto. Messaggi: venduto veloce e allarme preferiti.

| variabile | default | cosa fa |
|---|---|---|
| TRACCIAMENTO_ATTIVO | 1 | 0 spegne il tracciamento |
| VENDUTO_VELOCE_MARGINE_MIN | 40 | margine (EUR) per il messaggio, 0 = spento |
| ALLARME_PREF_ATTIVO | 1 | allarme sui preferiti in crescita |
| ALLARME_PREF_60 / _300 | 3 / 6 | preferiti a 60 s e 300 s |
| ALLARME_PREF_RAPPORTO | 1.5 | fair value/prezzo minimo |
| SKIP_GIA_VENDUTI | 0 | 1 scarta i gia' venduti |

## Cascate e quote Gemini
`bot/gemini_stato.py` (`cascata_per`, quote per coppia chiave-modello) e `bot/gemini_api.py`. Chiavi di `GEMINI_API_KEYS`; la cascata va dal modello migliore al piu' leggero e scala quando la quota giornaliera finisce su tutte le chiavi (reset a mezzanotte Pacific). Chiave 401/403: esclusa 6 ore. Dopo `GEMINI_TIMEOUT_PER_PAUSA` timeout di fila la fase salta Gemini per `GEMINI_PAUSA_TIMEOUT_SECONDI`.

| variabile | default | cosa fa |
|---|---|---|
| GEMINI_API_KEYS / GEMINI_API_KEY | vuote | chiavi gratuite (la singola e' il ripiego) |
| GEMINI_CASCATA / _OCCHIO | vuote | modelli in ordine, la seconda per le foto |
| GEMINI_MODEL_FALLBACK | gemini-3.1-flash-lite | modello di ripiego |
| GEMINI_BACKOFF_MAX_S / _BUDGET_CHIAMATA_S | 6 / 60 | backoff e budget per chiamata |
| GEMINI_TIMEOUT_S | 20 | timeout di una richiesta |
| GEMINI_TIMEOUT_PER_PAUSA / _PAUSA_TIMEOUT_SECONDI | 2 / 120 | timeout di fila e pausa |

## Telegram blocchi e limitatore
`bot/telegram_api.py`: limitatore di ritmo (`TELEGRAM_MSG_MINUTO` messaggi o foto in 60 s, oltre la chiamata aspetta), attesa dei blocchi 429 (`_attendi_fine_blocco`) e coda dei messaggi muti. I messaggi si aggiornano in place (didascalia max 1024 caratteri). Bottoni di feedback in `bot/feedback.py`.

| variabile | default | cosa fa |
|---|---|---|
| TELEGRAM_MSG_MINUTO | 14 | ritmo massimo, 0 = spento |
| TELEGRAM_ATTESA_MUTI_MAX_S | 3 | attesa massima per i muti |
| FEEDBACK_ATTIVO | 1 | 0 toglie i bottoni di feedback |
| TELEGRAM_ALERT_CHAT_ID | vuoto | gruppo COMPRA degli avvisi |

## Banda e contatori
`bot/proxy.py`: ogni risposta Vinted aggiorna i contatori di banda per tipo (`_registra_banda`), salvati nel DB; il log `RIEPILOGO BANDA` li riassume (procedura in `docs/procedure/consumi.md`). Quarantena dei proxy che falliscono di fila. `PROXY_LIST` e `PROXY_ESCLUSI` non si toccano.

| variabile | default | cosa fa |
|---|---|---|
| PROXY_QUARANTENA_SOGLIA | 3 | errori di fila prima della quarantena |
| PROXY_QUARANTENA_ORE | 3 | durata della quarantena |
| SONDA_BANDA_CAMPIONI | 10 | pagine misurate dalla sonda, 0 = spenta |
| LOG_DB / LOG_DB_MAX_MB | 1 / 0 | log nel DB e suo limite (0 = nessuno) |
| DB_FILE | /data/vinted_bot.sqlite3 | database sul volume |

## Pausa notturna
Sulla fonte: i tracker hanno `NIGHT_PAUSE_FROM/TO` (23-6 ora italiana; sono variabili dei servizi tracker, non del worker). Il worker non si ferma. Il radar ha in piu' `radar_in_pausa` (`bot/radar.py`): in quella fascia ignora i messaggi radar (motivo `pausa_notturna`).

| variabile | default | cosa fa |
|---|---|---|
| RADAR_PAUSA_DA | 23 | inizio pausa del radar (vuoto = nessuna) |
| RADAR_PAUSA_A | 6 | fine pausa del radar |
| REPORT_RADAR_ORA_UTC | 5 | ora UTC del report giornaliero |

## Arresto e watchdog
`main_telethon.py`: su SIGTERM il bot finisce le analisi in corso (moda e radar) per al massimo `ARRESTO_ATTESA_MAX_S`, poi si disconnette. `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` (100, variabile di Railway) deve restare sopra. `watchdog_messaggi` riavvia se il gruppo tracker tace; `_thread_blocco` se il ciclo e' bloccato.

| variabile | default | cosa fa |
|---|---|---|
| ARRESTO_ATTESA_MAX_S | 90 | attesa massima allo stop |
| WATCHDOG_MINUTI | 10 | minuti di silenzio prima del riavvio, 0 = spento |
| BLOCCO_SECONDI | 120 | battito mancante prima del riavvio, 0 = spento |

## Radar: filtro modelli
`bot/radar.py` (messaggi con `RADAR_MARCATORE`), `bot/radar_matrice.py` (`trova_modello`, `valuta_modello`, dati `data/radar_matrice.json`, tabella `docs/radar-matrice.md`), `bot/radar_famiglie.py` (`modello_famiglia`). Un titolo che cita un modello noto usa il suo buy max (margine, ROI, riserva per rischio, tolleranza); sopra `RADAR_SPESA_MAX` si scarta sempre.

| variabile | default | cosa fa |
|---|---|---|
| RADAR_ATTIVO | 1 | 0 ignora i messaggi radar |
| RADAR_PREZZO_MIN / RADAR_SPESA_MAX | 10 / 50 | prezzo minimo e spesa massima (EUR) |
| RADAR_MARGINE_MIN / RADAR_ROI_MIN | 50 / 100 | margine (EUR) e ROI (%) minimi |
| RADAR_RISERVA_PER_PUNTO | 0.03 | riserva per punto di rischio |
| RADAR_TOLLERANZA_BUY_MAX | 1.15 | tolleranza sul buy max |
| RADAR_CAMPIONE_SCARTI_OGNI | 10 | 1 scartato su N visitato lo stesso |
| RADAR_FAMIGLIE_NUOVE_ORA | 40 | valutazioni orarie delle famiglie nuove |

## Radar: comparabili e semaforo
`bot/radar_v2.py` (`analizza`, `rivaluta`): ricerca dei comparabili con cache, pre-filtro per ricerca, semaforo e giallo `quasi_roi`. Il verdetto va nel DB (`bot/archivio_radar.py`). Avvisi solo per i semafori di `RADAR_SEMAFORI`.

| variabile | default | cosa fa |
|---|---|---|
| RADAR_V2_CACHE_ORE | 24 | validita' della cache dei prezzi |
| RADAR_V2_PARALLELO | 2 | ricerche in parallelo |
| RADAR_V2_PREFILTRO / _RIF_ORE | 1 / 8 | pre-filtro e ore del riferimento |
| RADAR_V2_SCALA_MIN | 3 | comparabili minimi prima di allargare |
| RADAR_V2_MAX_GIORNO | 3000 | valutazioni massime al giorno |
| RADAR_QUASI_ROI_MIN / _JEV_CONF / _MIN_N | 90 / 0.85 / 8 | regola `quasi_roi` (0 = spenta) |
| RADAR_SEMAFORI | verde,giallo | semafori che avvisano |

## Radar: Jev
`bot/jev.py` (`giudica_completo`) e `bot/radar.py`: Jev giudica i comparabili e il modello; un giudizio sul "stesso modello" declassa il verde se i simili non reggono (`RADAR_VERIFICA`). Jev non alza mai un rosso, quindi si chiede solo a gialli, verdi e possibili `quasi_roi`.

| variabile | default | cosa fa |
|---|---|---|
| RADAR_JEV_RICHIESTO | 1 | Jev richiesto per l'avviso |
| RADAR_JEV_CONF_MIN | 0.7 | confidenza minima |
| RADAR_JEV_SOLO_UTILI | 1 | 0 = Jev su tutti |
| RADAR_VERIFICA / _VERIFICA_SCARTA | 1 / 0 | verifica "stesso modello"; 1 = scarta senza simili |
| JEV_GIUDICE / JEV_COMPS / JEV_FOTO_COMPS | 0 / 0 / 0 | prove in ombra |
| JEV_PRECONTROLLO / JEV_AUTENTICITA_FOTO | 1 / 5 | precontrollo e foto per l'autenticita' |

## Radar: Gemini
`bot/radar_gemini.py::controlla`: dopo semaforo e Jev, una chiamata Gemini gratuita sulle foto dei soli gialli e verdi. Esiti `conferma`, `dubbio` (parte muto, "da rivedere"), `scarta` (non parte). Legge il modello esatto: se la ricerca cambia, `rivaluta` rifa' comparabili e semaforo (un rosso non parte). La sua stima di rivendita e' solo informativa.

| variabile | default | cosa fa |
|---|---|---|
| RADAR_GEMINI | 1 | 0 spegne il controllo |
| RADAR_GEMINI_FOTO | 10 | foto massime per chiamata |
| RADAR_GEMINI_MAX_ORA | 40 | chiamate massime all'ora |
| RADAR_GEMINI_RAPPORTO_MIN | 0.5 | rapporto minimo con la stima del codice |

## Radar: appreso
`bot/radar_appreso.py` (`registra`, `limite_famiglia`, `da_saltare`, `carica_dal_db`): impara dai comparabili il prezzo sopra cui una famiglia non rende e salta in anticipo gli annunci sopra quel limite; 1 su N passa comunque per misurare.

| variabile | default | cosa fa |
|---|---|---|
| RADAR_APPRESO | 1 | 0 spegne l'apprendimento |
| RADAR_APPRESO_GIORNI | 14 | finestra dei dati |
| RADAR_APPRESO_CAMPIONE | 10 | 1 annuncio su N passa comunque, 0 = mai |
| RADAR_TRACCIA_ROSSI_1_SU | 10 | traccia 1 rosso su N |
| RADAR_AUDIT_1_SU | 20 | audit di 1 scarto "non oggetto" su N |

## Radar: spedizione
`bot/spedizione.py` (`costo_spedizione`, `classe_taglia`, `paese_da_html`): il costo di spedizione entra nel prezzo d'acquisto di margine e ROI, in base a paese del venditore e taglia dell'oggetto; i campi si leggono dalla pagina gia' scaricata.

| variabile | default | cosa fa |
|---|---|---|
| SPEDIZIONE_TARIFFE | vuoto | tariffe alternative (vuoto = quelle del codice) |

## Ramo Occhio e Cervello (rimosso)
Occhio e Cervello erano spenti dal 1/11 (`SOLO_SEMAFORO=1`) e sono stati tolti dal codice il 13/11. Si recuperano da git: vedi `_archive/2026-11-cervello/README.md`. Non esistono piu' le loro variabili.
