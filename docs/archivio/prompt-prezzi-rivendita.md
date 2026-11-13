# Prompt per la ricerca dei prezzi di rivendita (da usare in un'altra sessione)

Come usarlo: aprire una sessione con ricerca web, incollare il **PROMPT** qui sotto, poi incollare l'**ELENCO** dei modelli (una riga `marca|modello|categoria`, come `tools/radar_liste/lotto1.txt`). Lavorare a blocchi di 10-15 righe. Incollare qui l'output **JSON Lines** (una riga JSON per modello) e io lo trasformo in righe di `data/radar_matrice.json` e nelle liste del radar.

## PROMPT

Sei un analista di rivendita dell'usato. Per ogni riga `marca|modello|categoria` dell'elenco devi stimare a che prezzo si rivende **davvero e in fretta** in Italia/Europa un pezzo usato in buone condizioni, usando solo prezzi di vendite concluse.

REGOLE (vincolanti):
1. Fonti ammesse, in quest'ordine: venduti eBay (filtro "Venduti"/"Sold"), Catawiki e case d'asta (prezzo di martello senza diritti), Subito/Kleinanzeigen/Tradera/Marktplaats solo se mostrano "venduto". Gli annunci semplicemente in vendita (prezzo richiesto) NON sono prezzi di rivendita: usali solo come controllo e dichiaralo. Non usare vinted.it.
2. Prendi i venduti degli ultimi 12 mesi (max 24). Almeno 3 venduti per dare un numero "misurato". Con meno di 3 il numero e' una **stima** e va marcata `"stima": true` con `affidabilita` "bassa" o "insufficiente". Non inventare mai un numero: se non trovi nulla scrivi `null` e spiega.
3. `rivendita_veloce_eur` = 30° percentile dei venduti (il prezzo a cui si vende in pochi giorni); `rivendita_normale_eur` = mediana. Prezzi in EUR (cambi: 1 GBP=1,17; 1 USD=0,865; 1 SEK=0,09). Spedizione esclusa.
4. Stesso pezzo, stessa condizione: escludi ricambi, accessori, copie, "per pezzi", lotti, set incompleti, versioni diverse (indica nelle `note` le confusioni piu' comuni). Un modello con varianti di prezzo molto diverse va diviso in righe separate.
5. Condizione di riferimento: usato buono/ottimo, funzionante. Indica `condizione_riferimento`.
6. Rischio: `rischio_falsi` 1-5 (1 = nessuno, 5 = molti falsi), `segni_autenticita` (1 frase, cosa si vede in foto), `riconoscibile_da_foto` 1-5.
7. `chiavi`: da 2 a 6 modi in cui un venditore italiano scrive il titolo (minuscolo, senza accenti, marca inclusa, errori di ortografia comuni). `parole_escluse`: parole che nel titolo indicano accessorio/ricambio/copia per quel modello.
8. Per ogni modello cita le fonti: per ciascun venduto usato `{"prezzo_eur":..,"data":"AAAA-MM","fonte":"ebay|catawiki|asta|altro","url":".."}` (almeno i 3-8 piu' rappresentativi). Niente link inventati.
9. Se la ricerca e' ambigua o il modello non esiste, scrivi `"affidabilita":"insufficiente"` e spiega in `note`. Meglio un `null` onesto che un numero di fantasia.

OUTPUT: solo JSON Lines (una riga per modello, niente testo fuori, niente commenti), con questi campi:

{"brand":"","modello":"","categoria":"","chiavi":[],"parole_escluse":[],"rivendita_veloce_eur":0,"rivendita_normale_eur":0,"n_venduti":0,"periodo":"AAAA-MM..AAAA-MM","affidabilita":"alta|media|bassa|insufficiente","stima":false,"condizione_riferimento":"","spedizione_eur":0,"fragile":false,"ingombrante":false,"rischio_falsi":1,"riconoscibile_da_foto":3,"domanda":3,"segni_autenticita":"","venduti":[{"prezzo_eur":0,"data":"","fonte":"","url":""}],"controllo_richiesti":{"n":0,"mediana_eur":0},"note":""}

`domanda` 1-5 = quanto in fretta si vende (5 = giorni, 1 = mesi). Alla fine, dopo il JSON, una sola riga `RIEPILOGO: N modelli, X misurati, Y stime, Z senza dati`.

ELENCO:
(incollare qui le righe marca|modello|categoria)

## Cosa mi aspetto di ricevere
- Un blocco di righe JSON come sopra, una per modello. Le righe con `stima: true` le uso solo con asterisco (`*`) nel messaggio del radar, quelle con `rivendita_veloce_eur: null` restano senza lista (registrano soltanto).
- Il **buy max non lo calcolate voi**: lo calcolo io dal prezzo veloce, spedizione e rischio con la formula gia' nel bot (margine >= 50 EUR, ROI >= 100%).
- Se un modello vale meno di circa 100 EUR di rivendita veloce non puo' dare 50 EUR di margine: ditelo in `note`, lo marco `sotto_soglia`.
