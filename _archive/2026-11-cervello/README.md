# Occhio e Cervello (tolti il 13/11/2026)
Il ramo Occhio/Cervello della moda era spento dal 1/11 (`SOLO_SEMAFORO=1`) e il 13/11 e' stato tolto dal codice. Non c'e' codice qui: si recupera da git.
Commit di partenza: `2367005` (ultimo con il ramo completo e le variabili `SOLO_SEMAFORO`, `ANALISI_GEMINI`, `GALLERIA_ANTICIPATA`).
Moduli cancellati: `bot/verdetto.py`, `bot/occhio.py`, `bot/skip_report.py`, `bot/prompts.py`, `bot/schemas.py`, `bot/resellbot.py`.
Parti tolte: `chiama_gemini_cervello` (gemini_api), `search_comps_completo` e fonti Reddit/eBay/visuale (comps), `_invia_risultato_telegram`, `componi_testi_verdetto`, richiesta etichetta (scheda), cascate `*_CERVELLO` e `*_ALTO` (gemini_stato), `check_skip_rosso` (fair_value), controllo autenticita' proposto (feedback), costanti di soglia in config.
Spostati: `_a_float` e `_estrai_item_id_da_url` in `bot/parsing.py`.
