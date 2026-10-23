# Liste modelli del tracker `vinted-radar`

Script (copiati dalla sessione del 18/10) che scrivono i nomi delle ricerche del radar nel formato
`Nome :: !esclusioni comuni | chiave=rivendita/buymax[*][!esclusioni] | ...` e li caricano con POST su `/update_query/<id>`.
Il tracker (`davegnima/Vinted-Notifications`, `core.py`) avvisa solo se il titolo contiene una chiave e il prezzo e' 🟢/🟡/⚪.

- `rigenera.py`: rigenera TUTTE le liste (regole R1-R4 in testa al file, varianti, esclusioni per brand `ACC`, comuni `ACC_GEN`, `MODERNE`, `REPRO`, `ABITI`, `COPIE_LEGO`). Senza argomenti scrive solo `composti.json` (vecchio, nuovo per ricerca); con `--carica` aggiorna il radar. Poi verificare su `/queries` che le 131 ricerche combacino.
- Sorgenti dei prezzi: `data/radar_matrice.json` (tabella del bot, venduti reali), `genera.py` (fotografia F1-F3, `STIME`), `singole.py` (ricerche S, dict `L`), `studio_prezzi.py` (ricerche STUDIO, dict `S`, stime marcate `*`).
- `studio2.py base|controllo <etichetta>`: conteggio annunci registrati per ricerca (attenzione: `/items` ha limite 100 e ogni pagina pesa ~1,3 MB).
- `scarica24.py`: scarica fino a 1.500 annunci per ricerca con data (`d24.json`), per le analisi su finestre lunghe.
- `cfg_tool.py mostra|imposta k=v`: legge/modifica `/config` del tracker (`CFG_BASE` per la moda) senza stampare token, chat o proxy.
- `banwords.py`, `tetti.py` (price_to = buy max piu' alto x 1,15), `dividi.py`, `allarga.py`, `categorie.py`: passaggi del 18/10, gia' applicati.
- Tutti importano `envbot.py` (variabili finte per importare `bot/`); nessuna chiave vera nei file.
- `catalogo.py [--carica]`: mette il catalog id (categoria Vinted) nelle ricerche STUDIO di elettronica (tabella `MAPPA` nel file). Regole verificate il 23/10: con `catalog[]` il testo di ricerca puo' avere piu' parole (verificato 23/10: 'switch oled'+3025 e 'airpods pro'+3678 danno annunci; il '0 annunci' visto prima era una lettura anticipata della prova); gli id 23xx dell'albero "Intrattenimento" (es. 2420) non filtrano (0 annunci), gli id di Casa (es. 1940) si; id utili: 3025 console, 3678 cuffie, 3681 altoparlanti, 3035/3004 smartwatch, 3031 fitness tracker, 3074 action camera, 3075/3076 fotocamere, 3026 giochi, 3027 accessori console. Il payload di ricerca del tracker NON contiene il catalog id (provato con `LOG_CATALOG=1`, Vinted-Notifications #25/#26): per scoprire un id si aggiungono ricerche di prova `STUDIO test cat <id>` con una parola di ricerca su un intervallo di id e si leggono i titoli.
