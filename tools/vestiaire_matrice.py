"""Aggiunge categoria agli articoli Vestiaire e costruisce la matrice brand x categoria.

Uso: python3 tools/vestiaire_matrice.py docs/analisi/vestiaire_we_love.json
La categoria e' DEDOTTA dalle parole del titolo (il sito non la da' nei PDF):
quello che non riconosco resta "Altro". Prezzi: mediana per cella (prezzo_eur attuale).
"""
import csv
import json
import re
import statistics
import sys
from collections import defaultdict

TIPI = [  # (macro categoria, tipo, parole chiave nel titolo)
    ('Borse', 'Borsa', r'\b(borsa|borsello|tote|pochette|zaino|cartella|marsupio|mini bag|maxi bag|clutch|shopper|bauletto)\b'),
    ('Borse', 'Piccola pelletteria', r'\b(portamonete|portafoglio|porta |portachiavi|piccola)\b'),
    ('Scarpe', 'Sneakers', r'\b(sneakers|scarpe)\b'),
    ('Scarpe', 'Mocassini e ballerine', r'\b(mocassini|ballerine|décolleté|espadrillas)\b'),
    ('Scarpe', 'Sandali e ciabatte', r'\b(sandali|ciabatte|zoccoli|infradito)\b'),
    ('Scarpe', 'Stivali', r'\bstivali\b'),
    ('Gioielli e orologi', 'Orologi', r'\b(orologio|orologi)\b'),
    ('Gioielli e orologi', 'Gioielli', r'\b(orecchini|collier|collana|bracciale|anello|gioiello|spilla)\b'),
    ('Abbigliamento', 'Capispalla', r'\b(giubbotto|giacca|trench|giaccone|montgomery|cappotto|piumino|impermeabile|parka|blazer|gilet)\b'),
    ('Abbigliamento', 'Maglieria e top', r'\b(felpa|maglione|cardigan|t-shirt|maglietta|top|polo|camicia|camicetta|tunica)\b'),
    ('Abbigliamento', 'Pantaloni e gonne', r'\b(pantaloni|short|jeans|gonna|minigonna|leggings|salopette)\b'),
    ('Abbigliamento', 'Abiti e completi', r'\b(vestito|completo|tuta|bikini|bustino|twin-set|costume|body|canottiera|pareo|tailleur|lingerie|abito)\b'),
    ('Accessori', 'Cinture', r'\bcintura\b'),
    ('Accessori', 'Occhiali', r'\bocchiali\b'),
    ('Accessori', 'Sciarpe e cappelli', r'\b(sciarpa|stola|foulard|scaldacollo|berretto|panama|cappello|guanti)\b'),
]


def classifica(titolo):
    t = titolo.lower()
    for macro, tipo, rx in TIPI:
        if re.search(rx, t):
            return macro, tipo
    return 'Altro', 'Altro'


def cella(prezzi):
    return {'n': len(prezzi), 'mediana_eur': round(statistics.median(prezzi)),
            'min_eur': min(prezzi), 'max_eur': max(prezzi)}


if __name__ == '__main__':
    p = sys.argv[1]
    d = json.load(open(p))
    for a in d['articoli']:
        a['categoria'], a['tipo'] = classifica(a['titolo'])
    cats = ['Borse', 'Scarpe', 'Abbigliamento', 'Gioielli e orologi', 'Accessori', 'Altro']
    bc = defaultdict(lambda: defaultdict(list))
    ct = defaultdict(list)
    for a in d['articoli']:
        bc[a['brand']][a['categoria']].append(a['prezzo_eur'])
        ct[(a['categoria'], a['tipo'])].append(a['prezzo_eur'])
    righe = sorted(bc, key=lambda b: -sum(len(v) for v in bc[b].values()))
    matrice = []
    for b in righe:
        tot = [x for v in bc[b].values() for x in v]
        matrice.append({'brand': b, 'totale': cella(tot),
                        **{c: (cella(bc[b][c]) if bc[b].get(c) else None) for c in cats}})
    d['categorie_note'] = 'categoria e tipo dedotti dalle parole del titolo; Altro = non riconosciuto'
    d['per_categoria'] = {f'{c} / {t}': cella(v) for (c, t), v in sorted(ct.items(), key=lambda x: -len(x[1]))}
    d['matrice_brand_categoria'] = matrice
    json.dump(d, open(p, 'w'), ensure_ascii=False, indent=1)
    base = p.rsplit('.', 1)[0]
    with open(base + '_matrice.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['brand', 'totale_n', 'totale_mediana_eur'] + [x for c in cats for x in (f'{c}_n', f'{c}_mediana_eur')])
        for r in matrice:
            w.writerow([r['brand'], r['totale']['n'], r['totale']['mediana_eur']] +
                       [x for c in cats for x in ((r[c]['n'], r[c]['mediana_eur']) if r[c] else ('', ''))])
    with open(base + '_matrice.md', 'w') as f:
        f.write('# Vestiaire We Love: brand x categoria (n articoli · prezzo mediano €)\n\n')
        f.write('Categoria dedotta dal titolo. Campione: %d articoli.\n\n' % len(d['articoli']))
        f.write('| Brand | Tot | ' + ' | '.join(cats) + ' |\n|---|---|' + '---|' * len(cats) + '\n')
        for r in matrice:
            f.write(f"| {r['brand']} | {r['totale']['n']} · {r['totale']['mediana_eur']} | " +
                    ' | '.join((f"{r[c]['n']} · {r[c]['mediana_eur']}" if r[c] else '') for c in cats) + ' |\n')
    n_altro = sum(1 for a in d['articoli'] if a['categoria'] == 'Altro')
    print(len(righe), 'brand; Altro =', n_altro)
    print({k: v['n'] for k, v in d['per_categoria'].items()})
