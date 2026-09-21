"""Meta Ads (Facebook/Instagram) package — paralelo a src/google_ads/.

Sprint M.2a establishes: client.py (constantes + erros do gate — era a fábrica
do `FacebookAdsApi`, que saiu no F190 junto com o SDK), reports.py (executor de
GET na Graph API, hoje em httpx com token no header), errors.py (mapeamento
PT-BR dos erros da Graph).

Future sprints (M.3+) add: insights/ (Insights API builders), mutates/
(mutation builders), enum_to_label.py (Meta enum → PT-BR labels).
"""
