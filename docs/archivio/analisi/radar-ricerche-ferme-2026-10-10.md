# Ricerche del tracker radar al momento dello stop (10/10)

L'utente ha fermato il test del radar il 10/10: servizio `vinted-radar` fermato e `RADAR_ATTIVO=0` nel worker.
Per ripartire: rimettere `RADAR_ATTIVO=1` (o togliere la variabile), ridistribuire `vinted-radar`, controllare che queste ricerche ci siano ancora nella pagina `/queries` (altrimenti reinserirle con POST `/add_query`, campi `query` e `query_name`). Le 12 sospese il 9/10 sono in `radar-ricerche-sospese-2026-10-09.md`.

42 ricerche:

| Id | Nome | URL |
|---|---|---|
| 1 | R lego ucs | https://www.vinted.it/catalog?search_text=ucs&catalog%5B%5D=1767&brand_ids%5B%5D=89162&currency=EUR&price_to=50&order=newest_first |
| 2 | R lego technic | https://www.vinted.it/catalog?search_text=technic&catalog%5B%5D=1767&brand_ids%5B%5D=89162&currency=EUR&price_to=50&order=newest_first |
| 3 | R lego ideas | https://www.vinted.it/catalog?search_text=ideas&catalog%5B%5D=1767&brand_ids%5B%5D=89162&currency=EUR&price_to=50&order=newest_first |
| 4 | R lego star wars | https://www.vinted.it/catalog?search_text=star+wars&catalog%5B%5D=1767&brand_ids%5B%5D=89162&currency=EUR&price_to=50&order=newest_first |
| 5 | R game boy | https://www.vinted.it/catalog?search_text=game+boy&catalog%5B%5D=3026&currency=EUR&price_to=40&order=newest_first |
| 6 | R game boy micro | https://www.vinted.it/catalog?search_text=game+boy+micro&currency=EUR&price_to=50&order=newest_first |
| 7 | R new 3ds xl | https://www.vinted.it/catalog?search_text=new+3ds+xl&currency=EUR&price_to=50&order=newest_first |
| 14 | R lego modular | https://www.vinted.it/catalog?search_text=modular&catalog%5B%5D=1767&brand_ids%5B%5D=89162&currency=EUR&price_to=50&order=newest_first |
| 16 | R persol | https://www.vinted.it/catalog?catalog%5B%5D=98&catalog%5B%5D=26&brand_ids%5B%5D=12775&currency=EUR&price_to=50&order=newest_first |
| 17 | R oliver peoples | https://www.vinted.it/catalog?search_text=oliver+peoples&catalog%5B%5D=98&catalog%5B%5D=26&currency=EUR&price_to=50&order=newest_first |
| 19 | R contax | https://www.vinted.it/catalog?search_text=contax&currency=EUR&price_to=50&order=newest_first |
| 21 | R matsuda | https://www.vinted.it/catalog?search_text=matsuda&catalog%5B%5D=98&catalog%5B%5D=26&currency=EUR&price_to=50&order=newest_first |
| 22 | R cazal | https://www.vinted.it/catalog?search_text=cazal&catalog%5B%5D=98&catalog%5B%5D=26&currency=EUR&price_to=50&order=newest_first |
| 23 | R jacques marie mage | https://www.vinted.it/catalog?search_text=jacques+marie+mage&catalog%5B%5D=98&catalog%5B%5D=26&currency=EUR&price_to=50&order=newest_first |
| 24 | R mulberry | https://www.vinted.it/catalog?search_text=mulberry&catalog%5B%5D=156&catalog%5B%5D=158&catalog%5B%5D=161&catalog%5B%5D=552&currency=EUR&price_to=50&order=newest_first |
| 25 | R roberta di camerino | https://www.vinted.it/catalog?search_text=roberta+di+camerino&catalog%5B%5D=156&catalog%5B%5D=158&catalog%5B%5D=161&catalog%5B%5D=552&currency=EUR&price_to=50&order=newest_first |
| 26 | R coach vintage | https://www.vinted.it/catalog?search_text=coach+vintage&catalog%5B%5D=156&catalog%5B%5D=158&catalog%5B%5D=161&catalog%5B%5D=552&currency=EUR&price_to=50&order=newest_first |
| 29 | R minolta tc-1 | https://www.vinted.it/catalog?search_text=minolta+tc-1&currency=EUR&price_to=50&order=newest_first |
| 31 | R olympus mju | https://www.vinted.it/catalog?search_text=olympus+mju&currency=EUR&price_to=50&order=newest_first |
| 32 | R lacroix | https://www.vinted.it/catalog?search_text=lacroix&catalog%5B%5D=1957&catalog%5B%5D=1952&currency=EUR&price_to=50&order=newest_first |
| 33 | R ysl bijoux | https://www.vinted.it/catalog?search_text=ysl+orecchini&currency=EUR&price_to=50&order=newest_first |
| 34 | R yashica t4 | https://www.vinted.it/catalog?search_text=yashica+t4&currency=EUR&price_to=50&order=newest_first |
| 35 | R yashica t5 | https://www.vinted.it/catalog?search_text=yashica+t5&currency=EUR&price_to=50&order=newest_first |
| 36 | R ricoh gr1 | https://www.vinted.it/catalog?search_text=ricoh+gr1&currency=EUR&price_to=50&order=newest_first |
| 37 | R nikon 35ti | https://www.vinted.it/catalog?search_text=nikon+35ti&currency=EUR&price_to=50&order=newest_first |
| 38 | R rollei 35 | https://www.vinted.it/catalog?search_text=rollei+35&currency=EUR&price_to=50&order=newest_first |
| 39 | R fujifilm klasse | https://www.vinted.it/catalog?search_text=fujifilm+klasse&currency=EUR&price_to=50&order=newest_first |
| 40 | R leica minilux | https://www.vinted.it/catalog?search_text=leica+minilux&currency=EUR&price_to=50&order=newest_first |
| 41 | R nikon fm2 | https://www.vinted.it/catalog?search_text=nikon+fm2&currency=EUR&price_to=50&order=newest_first |
| 42 | R olympus pen f | https://www.vinted.it/catalog?search_text=olympus+pen+f&currency=EUR&price_to=50&order=newest_first |
| 43 | R summicron | https://www.vinted.it/catalog?search_text=summicron&currency=EUR&price_to=50&order=newest_first |
| 44 | R nikkor 1.2 | https://www.vinted.it/catalog?search_text=nikkor+1.2&currency=EUR&price_to=50&order=newest_first |
| 45 | R canon fd 1.2 | https://www.vinted.it/catalog?search_text=canon+fd+1.2&currency=EUR&price_to=50&order=newest_first |
| 46 | R walkman dd | https://www.vinted.it/catalog?search_text=walkman+dd&currency=EUR&price_to=50&order=newest_first |
| 47 | R game watch | https://www.vinted.it/catalog?search_text=game+watch&currency=EUR&price_to=50&order=newest_first |
| 48 | R conker | https://www.vinted.it/catalog?search_text=conker&currency=EUR&price_to=50&order=newest_first |
| 49 | R montblanc 149 | https://www.vinted.it/catalog?search_text=montblanc+149&currency=EUR&price_to=50&order=newest_first |
| 50 | R seiko 6139 | https://www.vinted.it/catalog?search_text=seiko+6139&currency=EUR&price_to=50&order=newest_first |
| 51 | R vivianna torun | https://www.vinted.it/catalog?search_text=vivianna+torun&currency=EUR&price_to=50&order=newest_first |
| 52 | R panthella | https://www.vinted.it/catalog?search_text=panthella&currency=EUR&price_to=50&order=newest_first |
| 53 | R vitra miniature | https://www.vinted.it/catalog?search_text=vitra+miniature&currency=EUR&price_to=50&order=newest_first |
| 54 | R loewe amazona | https://www.vinted.it/catalog?search_text=loewe+amazona&currency=EUR&price_to=50&order=newest_first |
