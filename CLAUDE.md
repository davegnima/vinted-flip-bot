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
tracker (messaggio Telegram) -> `process_listing` (`bot/pipeline.py`) -> scrape pagina e foto -> stima rapida fair value -> Occhio (Gemini, vision) -> filtri pre-Cervello -> Cervello (JSON; mediana di 3 campioni solo per COMPRA/TRATTA) -> `calcola_verdetto` (deterministico: decisione da margine e ROI) -> messaggio Telegram.
- Il modello non calcola margine/ROI/decisione: lo fa Python (`bot/verdetto.py`). Dal 7/10 due vie in piu' al COMPRA: capo sottoprezzato (prezzo <= `SOGLIA_PREZZO_BASSO_COMPRA` 20 EUR con margine >= 20, oppure target >= `SOGLIA_RAPPORTO_TARGET_COMPRA` x3 il prezzo con margine >= 15) e legit "sospetto" con margine >= `SOGLIA_MARGINE_COMPRA_SOSPETTO` (80 EUR; `non_verificabile` resta CHIEDI ALTRE FOTO).
- Fascia Gemini scelta prima dell'Occhio da `ruoli_gemini` (stima rapida verde/gialla = alta; rossa = alta solo se prezzo >= `GEMINI_SOGLIA_PREZZO_ALTO`; stima a confidenza bassa = si sceglie dal prezzo).
- Stima rapida (`stima_fair_value`): ogni annuncio con brand ha un semaforo. Soglie dal 7/10: 🟢 ROI >= 200% (fair value x3) e margine >= 20; 🟡 ROI >= 100%; rigore confidenza bassa 1,0. Ordine: tabella dati -> appreso dai verdetti -> livello del brand x fattore categoria -> livello di default. Categoria da titolo, descrizione o catalogo Vinted (mappa che si impara sola: `CATALOGO_CATEGORIE_FILE`). Stime a confidenza bassa: soglie del semaforo x `FAIR_VALUE_RIGORE_BASSA` (1,0 dal 7/10); voci non apprese x `FAIR_VALUE_TARATURA_GLOBALE` (1,20; Missoni prima linea +10%, Cucinelli +15% in piu', da `FAIR_VALUE_TARATURA_BRAND`).
- Cascate Gemini per fase, dal modello migliore al piu' leggero: `bot/gemini_stato.py`. 4 account Google (ora 5), quote per (key, modello). La quota giornaliera free si azzera a mezzanotte di Pacific (07:00 UTC con l'ora legale): i cooldown di quota finiscono li', non al "retry in 23h" di Google. Una key che risponde 401/403 (cancellata o disabilitata) si esclude per 6 ore per ogni modello e si passa alla successiva; il log dice `key #N NON VALIDA` e quante ne restano. Stallo/timeout di Gemini (5/10: annunci fermi 5-8 minuti): backoff al massimo `GEMINI_BACKOFF_MAX_S` (6 s), budget `GEMINI_BUDGET_CHIAMATA_S` (60 s) per chiamata, riga `Gemini TIMEOUT | fase | modello | dopo Ns`, e dopo `GEMINI_TIMEOUT_PER_PAUSA` (2) timeout di fila la fase salta Gemini per `GEMINI_PAUSA_TIMEOUT_SECONDI` (120) e va alla riserva.
- Riserva a scalata via OmniRoute (`bot/riserva_llm.py`): spenta finche' `RISERVA_OCCHIO_MODELLI` / `RISERVA_CERVELLO_MODELLI` sono vuote. Attiva dal 4/10 (Gemini senza quota). Ultima riserva a pagamento (chiave Google dell'utente): dopo i modelli gratuiti se falliscono, prima di loro se sono troppo lenti (mediana ultime 3 risposte > `RISERVA_LENTA_MS`, 20 s, per `RISERVA_LENTA_PAUSA_S`); si torna sul gratuito da soli. E' accesa solo se `GEMINI_API_KEY` e' una chiave DISTINTA da quelle di `GEMINI_API_KEYS`: all'avvio il log dice `Riserva a pagamento ATTIVA/SPENTA` e perche'. Vale anche per l'Occhio (ultima spiaggia, endpoint compatibile OpenAI di Google con le foto). Riserva 6/10: Cervello `cerebras/gpt-oss-120b`, `nvidia/.../nemotron-3-super`, `openrouter/.../nemotron-3-ultra:free`, `mistral/codestral-latest`; Occhio `openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (OpenRouter :free = 50 richieste al giorno). Dopo un 429 di Gemini la fase salta Gemini per `GEMINI_PAUSA_429_SECONDI` (300) e va dritta alla riserva; poi riprova. Il target dei modelli di riserva si corregge con `RISERVA_FATTORI_TARGET` (Ministral 14B 1,0; gpt-oss-120b 0,95; gpt-oss-20b 0,55).
- Risparmio Gemini (4/10): campioni extra del Cervello 1 (`CERVELLO_CAMPIONI_EXTRA`, 2 campioni in totale); fascia alta solo con stima 🟢/🟡 a confidenza alta/media; rosso sicuro (🔴, confidenza alta/media, margine rapido negativo, prezzo < `GEMINI_SOGLIA_PREZZO_ALTO`) salta il Cervello: esito `SKIP_ROSSO`, spento con `SALTA_CERVELLO_ROSSO=0`.
- Preavviso (`valuta_preavviso` in `bot/fair_value.py`): un album con TUTTE le foto e il semaforo parte nel gruppo COMPRA (`TELEGRAM_ALERT_CHAT_ID`, con suono) appena le foto sono scaricate, se la stima rapida e' promettente; a fine analisi lo stesso messaggio viene AGGIORNATO col verdetto (didascalia, max 1024 caratteri), senza altri messaggi nel gruppo; se l'annuncio viene scartato prima del verdetto, la riga finale riporta il motivo e il link al messaggio originale nella chat principale (solo se e' un supergruppo) (senza gruppo, la scheda in chat principale diventa push) (soglie `PREAVVISO_*`, spento con `PREAVVISO_ATTIVO=0`); non cambia il semaforo. Dal 5/10: regola `prezzo_basso` a <= 20 EUR; brand esclusi `PREAVVISO_BRAND_ESCLUSI` (Acne Studios, Marni), brand facili `PREAVVISO_BRAND_FACILI` (Jean Paul Gaultier, regola `brand_facile`, margine >= `PREAVVISO_MARGINE_FACILI`); suono solo se fair value/prezzo >= `PREAVVISO_SUONO_RAPPORTO_MIN` (4) o brand facile, gli altri arrivano in silenzio (`suono=si|no` nella riga `PREAVVISO`).
- Scrape pagina annuncio (`bot/vinted_scrape.py`): se la risposta e' 200 ma leggera (< `PAGINA_LEGGERA_MAX_CARATTERI`, 60000: dal 6/10 14:17 UTC Vinted serve ai bot una pagina di ~20 KB senza foto) si riprova `PAGINA_LEGGERA_RETRY` (2) volte con un altro proxy e il log `Pagina annuncio leggera` riporta title, parole di blocco e testi visibili.
- Pannello in ombra (`bot/panel.py`): modelli extra via OmniRoute, solo log `PANEL | ...`, mai nel verdetto.
- Tracciamento vendite (`bot/tracciamento.py`): ricontrolli a 15 s, 30 s, 1 min, 5 min, 15 min, 1 h. `stato=rimosso?` = pagina 200 senza dati (cancellata o in revisione: non e' un invenduto, nessuna classe); `n.d.` = nessuna risposta. Gli annunci spariti (rimosso, rimosso?, n.d.) si seguono comunque fino a 1 h: righe `RICONTROLLO STORIA` (serie degli stati) e `RICONTROLLO RIAPPARSO` (tornati online: legit check, non ban). Dal 5/10 si seguono (solo fino a 5 min) anche gli scartati `FALSO CONCLAMATO` / `ANNUNCIO FRAUDOLENTO`, e `ERRORE_CERVELLO` con la serie completa.
- Radar fuori moda (`bot/radar.py`, fase 0 dal 7/10, SOLO osservazione: niente messaggi, niente AI): messaggi del tracker con `RADAR_MARCATORE` (📡) in testa o dalla chat `RADAR_GROUP_ID` saltano la pipeline moda. Modulo categoria da brand/parole (`RADAR_MODULI`, i 30 brand dell'utente), filtro di livello 1 su titolo e prezzo (parole vietate tipo rotto/per pezzi/stile, tetto `prezzo_max_l1`); chi passa (piu' 1 scartato su `RADAR_CAMPIONE_SCARTI_OGNI`) fa la visita della pagina senza guardaroba e la serie di ricontrolli con esito `RADAR_L1_PASSA`/`RADAR_L1_CAMPIONE`. Log `RADAR |`, `RADAR SCARTO |`, `MESSAGGIO RADAR |`; evento `radar` nel DB.
- SQLite (`bot/db.py`, `/data/vinted_bot.sqlite3`): quote Gemini e eventi. I log restano la fonte del recap.

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
- `python3 -m pytest -q` (143 test) e `python3 -m pyflakes main_telethon.py bot` (nomi non definiti). La CI (`.github/workflows/ci.yml`) fa lo stesso su Python 3.13.
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
   - vendite rapide: `"RICONTROLLO LAMPO"`; preavviso push (una riga per annuncio, con semaforo, regola e caratteristiche: categoria, condizione, materiale, taglia, lingua, n. foto, venditore, ora): `"PREAVVISO |"`; tempi del preavviso (pubblicazione -> telegram -> preavviso, secondi di invio): `"PREAVVISO_INVIATO |"`; le righe `RICONTROLLO LAMPO` e `PREAVVISO` portano i `preferiti` letti dalla pagina; `PREAVVISO` ha anche `fonte_cat` (titolo, descrizione, catalogo o nessuna); le righe `ESITO` portano `item=` per incrociarle con `PREAVVISO` e `RICONTROLLO LAMPO`
   - banda proxy: `"RIEPILOGO BANDA"`
   - radar fase 0: `"RADAR |"` (visitati), `"RADAR SCARTO |"` (scartati al livello 1), `"MESSAGGIO RADAR"`; i ricontrolli radar hanno `esito=RADAR_L1_*` nelle righe `RICONTROLLO LAMPO` (da tenere fuori dal recap moda)
5. Dopo un deploy controllare solo righe successive all'avvio (`"Vinted Oracle avviato"` riporta la versione).
6. Se non arrivano annunci analizzati (traffico basso, es. sabato sera) dirlo e aspettare, non rileggere in loop.

## Convenzioni
- Codice e commenti in italiano, stile come quello vicino. Niente modifiche a `prompts.py` senza motivo: le calibrazioni per brand sono frutto di dati reali.
- Il pannello e la riserva usano `@c` in coda al modello per il prompt compatto; il suffisso non va mai al gateway.
- Verificare la CI prima di ogni merge; non fare push forzati su branch altrui.
