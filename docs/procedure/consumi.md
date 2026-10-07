# Consumi: banda proxy e quote Gemini

**Scopo**: restare nei limiti (proxy 250 GB al mese; Gemini gratuito circa 500 richieste al giorno per account sui Flash Lite; chiave a pagamento con tetto `PAGAMENTO_MAX_RICHIESTE_GIORNO`).

**Input**: nessuno; da fare dopo ogni cambio di volume (ricerche, ricontrolli, nuove pipeline) e nel recap.

**Passi**
1. Banda: righe `"RIEPILOGO BANDA"` (MB dall'avvio del worker); prendere due righe distanti e calcolare MB/ora -> GB/giorno -> GB/mese. Indicare la voce che pesa di piu' (`pagina_annuncio` di solito).
2. Tracker: le letture delle ricerche passano dai proxy del tracker e non compaiono nel riepilogo del worker; stimarle a parte se servono.
3. Gemini: `"GEMINI_USO"` per modello, `"429"`, `"key #"` (NON VALIDA), `"RISERVA |"` e `PAGAMENTO richieste_oggi`.
4. Oltre budget: ridurre prima il volume inutile (filtri, prezzi minimi, ricontrolli), poi la frequenza.

**Formato**: GB/giorno e proiezione al mese rispetto a 250; richieste Gemini oggi per modello; cosa e' stato ridotto.

**Esempio reale (7/10)**: 1,15 GB in 1h40 dopo il radar = ~20 GB/giorno (pagina_annuncio 90%, ~300 KB a pagina) -> prezzo minimo 10 EUR e 3 ricontrolli invece di 6 (davegnima/vinted-flip-bot#88).

**Controllo finale**
- [ ] GB/giorno calcolati su almeno 1 h di dati?
- [ ] Proiezione mensile confrontata con 250 GB?
- [ ] Richieste a pagamento contate?
