# Stato del progetto (aggiornato 2026-10-07)

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

- Quota Gemini finita (4/10 16:35 UTC): `gemini-3.1-flash-lite` 500 richieste/giorno per account, tutte e 4 le chiavi esaurite, reset a mezzanotte di Pacific (07:00 UTC con l'ora legale, 09:00 in Italia), non a 00:00 UTC. Riserva attivata: Occhio `mistral/ministral-14b-2512`; Cervello `mistral/ministral-14b-2512@c`, `groq/openai/gpt-oss-120b@c`. Fattori sul target di riserva (mediana target modello / target Gemini sul pannello 2-3/10: Ministral 0,93 su 38 casi, gpt-oss-120b 0,96 su 8, gpt-oss-20b 2,0 su 5 molto dispersi; l'1,4-2x visto il 4/10 era un solo caso). Risparmio: 1 campione extra, fascia alta solo con stima solida, SKIP_ROSSO. Da controllare nel recap: righe `RISERVA |`, esiti con `riserva=`, quanti `SKIP_ROSSO` e quanti di questi vendono in fretta (falsi negativi), COMPRA di riserva vs Gemini.

- Pausa Gemini dopo 429 (PR cascata-429): la fase (occhio/cervello) salta Gemini per 5 minuti dopo un 429 e usa la riserva; `gemini_cascata_esaurita` conta anche i modelli esclusi. Verificare nei log che spariscano i 429 ripetuti e che `RISERVA |` copra Occhio e Cervello.

- Riserva a pagamento (PR gemini-pagamento): usa la variabile Railway `GEMINI_API_KEY` (la chiave a pagamento dell'utente; le gratuite sono in `GEMINI_API_KEYS`); spenta se `GEMINI_API_KEY` e' anche nella rotazione; `GEMINI_MODELLO_PAGAMENTO` (default gemini-3.1-flash-lite), tetto `PAGAMENTO_MAX_RICHIESTE_GIORNO` (600 al giorno UTC). Log: `RISERVA | fase | pagamento/... | ok | ... PAGAMENTO richieste_oggi=N/M`. Nel recap contare le richieste a pagamento e stimare la spesa.
- Tempi da caricato (PR tempi-da-caricato): se la pagina non espone `created_at` (succede quasi sempre), l'ora di caricamento si ricava dal "Caricato N secondi fa" letto allo scrape (`t_scrape` - N). Errore tipico 1-2 s; con unita' in minuti o ore i tempi hanno `~`. Nel preavviso: `⏱ caricato→telegram · telegram→preavviso · totale`. Controllare nei log `PREAVVISO_INVIATO` che `pub_telegram` e `pub_preavviso` ci siano.
- Recap 5/10, tappa 2 (PR tracciamento-preavviso): `stato=rimosso?` per le pagine 200 senza dati (prima `attivo?` e a 60 min finivano NON AFFARE a torto; ~37 su 83 erano cosi'), `n.d.` per nessuna risposta; scartati falso/fraudolento seguiti fino a 5 min (stima +85 MB/giorno), ERRORE_CERVELLO con serie completa; preavviso: `prezzo_basso` <= 20 EUR, Acne e Marni esclusi, Jean Paul Gaultier `brand_facile`, suono solo con fv/prezzo >= 4. Gli spariti si seguono fino a 1 h (`RICONTROLLO STORIA`, `RICONTROLLO RIAPPARSO`): capire quanti tornano online (legit check) e quanti restano spariti (ban/cancellati). Da controllare nel recap: righe `rimosso?` a parte, scartati falsi poi venduti rapidamente (falsi negativi), push al giorno e con `suono=si`, banda `RIEPILOGO BANDA`.
- 5/10 ~11:25-11:38 UTC: Gemini 401 "bound service account deleted or disabled" (chiave Google cancellata) e riserva 401 "Invalid API key" dal gateway OmniRoute (`EXTRA_LLM_KEY` non allineata): ERRORE_CERVELLO su piu' annunci. Fix #80: 401/403 di Gemini segna la key non valida e ruota. Da fare dall'utente: aggiornare `GEMINI_API_KEYS` (e `GEMINI_API_KEY` se toccata) ed `EXTRA_LLM_KEY` sul worker.
- 5/10 14:01-14:09 UTC: stallo di Gemini, ~10 annunci fermi 5-8 min (Jean 44 Thierry Mugler COMPRA 5m55s). Causa: timeout 30 s + backoff raddoppiato senza tetto, nessun log. Fix #81: tetto backoff, budget 60 s, riga `Gemini TIMEOUT`, pausa dopo 2 timeout di fila. Da controllare: righe `Gemini TIMEOUT` (quanti, quale fase/modello), `RISERVA |` dopo i timeout, `Tempi pipeline` con cervello/occhio > 60 s.
- 6/10: dalle 14:17 UTC gli scrape danno pagine da ~20 KB senza foto (tutti i proxy): PR retry+diagnostica pagina leggera; da leggere nei log `Pagina annuncio leggera` per capire se e' un blocco/sfida. Riserva: Mistral `ministral-14b-2512` non e' piu' nel catalogo OmniRoute (400); `RISERVA_CERVELLO_MODELLI` e `PANEL_CERVELLO_MODELLI` passati a `mistral/codestral-latest@c` (codestral non vede le immagini: l'Occhio di riserva resta senza modello valido, serve un modello Mistral con visione, es. mistral-small/pixtral, se nel catalogo). Groq/Z.ai/NVIDIA senza chiavi in OmniRoute. Key Gemini #3 non valida il 6/10 14:46 UTC (3 su 4 valide): da togliere da `GEMINI_API_KEYS`.
- 6/10 sera: Mistral Ministral fuori catalogo OmniRoute (lasciato); riserva ora: Cervello `cerebras/gpt-oss-120b@c`, `nvidia/nvidia/nemotron-3-super-120b-a12b@c`, `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free@c`, `mistral/codestral-latest@c`; Occhio `openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`; pannello Cervello: nemotron-3-super, cerebras gpt-oss-120b, codestral (OpenRouter fuori dal pannello per non finire i 50 al giorno); `PANEL_OCCHIO_MODELLI` vuoto. La riserva a pagamento NON e' mai scattata (nessuna riga PAGAMENTO): probabile `GEMINI_API_KEY` presente anche in `GEMINI_API_KEYS` -> spenta; PR con log di avvio che lo dice. Da verificare: l'utente controlla che `GEMINI_API_KEY` sia la chiave Google a pagamento e non sia nell'elenco gratuito.

- 7/10, analisi 4-7/10 (1031 annunci con vendita tracciata; "veloci" = venduti entro 15 min, media 24%): COMPRA 54% veloci, CHIEDI ALTRE FOTO 43%, TRATTA 19%, NON COMPRARE 12%. Rapporto target/prezzo: <1,5 9%, 2-3 24%, 3-5 53%, >5 65%. COMPRA <= 20 EUR 67%, > 80 EUR 29%. ⚠️ dati deboli non predice vendite lente. PR verdetto-semaforo: COMPRA anche per capo sottoprezzato (<= 20 EUR e margine >= 20, o target x3 e margine >= 15) e per "sospetto" con margine >= 80; semaforo ritarato (🟢 ROI >= 200% e margine >= 20, 🟡 ROI >= 100%, rigore bassa 1,0: in-sample 🟢 44%, 🟡 21%, 🔴 12%, prima 36/17/11). Da verificare nel recap: precisione dei nuovi COMPRA ("sottoprezzato", "autenticita' sospetta" nei limiti), quota 🟢, preavvisi al giorno (scendono), annunci in fascia alta Gemini (scendono). Da guardare dopo: fair value rapida sopra il target del Cervello per Courrèges bassa (x1,84), Miu Miu bassa (x1,65), Max Mara stima (x1,53); sotto per Jacquemus (x0,64) e Acne (x0,79).
- 7/10: chiave a pagamento `GEMINI_API_KEY` risponde 401 "bound service account deleted or disabled" (va rigenerata); Occhio di riserva senza modello funzionante (Nemotron OpenRouter 502); Cervello di riserva ok (cerebras gpt-oss-120b, codestral); key #3 gia' tolta. PR #83 unita (log `Riserva a pagamento ATTIVA/SPENTA`).

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
- Il recap mattutino (routine 07:42 Europe/Rome) arriva in questa sessione.
