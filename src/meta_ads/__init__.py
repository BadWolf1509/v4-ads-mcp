"""Meta Ads (Facebook/Instagram) package — paralelo a src/google_ads/.

client.py (constantes + erros do gate — era a fábrica do `FacebookAdsApi`, que
saiu no F190 junto com o SDK), reports.py (executor de GET na Graph API, em httpx
com token no header), errors.py (mapeamento PT-BR dos erros da Graph), labels.py
(enum Meta → rótulo PT-BR) e os módulos de leitura por assunto (colecao,
entidades, insights, saldo, pacing, moeda...). As mutações Meta não vivem aqui.
"""
