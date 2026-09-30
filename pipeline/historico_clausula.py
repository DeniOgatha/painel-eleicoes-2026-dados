# -*- coding: utf-8 -*-
"""
Mantem historicos em site/*.json: listas de "retratos" (snapshots) ao longo
do tempo. Usado hoje para dois arquivos:
  - historico-clausula.json: um ponto por atualizacao PUBLICADA com sucesso
    (chamado pelo update.py depois que a checagem de sanidade aprova - nunca
    antes, pra nunca guardar um ponto que na verdade foi rejeitado).
  - historico.json: linha do tempo geral (apuracao nacional + lideranca dos
    cargos majoritarios), um ponto por rodada com dado NOVO da fonte (ver
    `ultimo_ponto` + dedup em update.py) - independe de publicar/nao publicar,
    pra poder acompanhar a progressao mesmo testando local com --no-push.

Formato: lista de objetos em ordem cronologica crescente. Arquivo pequeno
(poucos KB por ponto), servido como estatico igual o live.json.
"""
import json
import os

MAX_PONTOS = 3000  # segurança contra crescimento sem fim (~varios dias de atualizacao a cada minuto)


def apender(site_dir, snapshot, max_pontos=MAX_PONTOS, nome_arquivo="historico-clausula.json"):
    path = os.path.join(site_dir, nome_arquivo)
    historico = []
    if os.path.isfile(path):
        try:
            historico = json.load(open(path, encoding="utf-8"))
            if not isinstance(historico, list):
                historico = []
        except ValueError:
            historico = []

    historico.append(snapshot)
    if len(historico) > max_pontos:
        historico = historico[-max_pontos:]

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(historico, fh, ensure_ascii=False, separators=(",", ":"))

    return path, len(historico)


def ultimo_ponto(site_dir, nome_arquivo):
    """Devolve o ultimo ponto salvo em site/<nome_arquivo>, ou None se o
    arquivo nao existe/esta vazio/corrompido. Usado pra decidir se vale a
    pena apender um ponto novo (dedup por chave escolhida pelo chamador)."""
    path = os.path.join(site_dir, nome_arquivo)
    if not os.path.isfile(path):
        return None
    try:
        historico = json.load(open(path, encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(historico, list) or not historico:
        return None
    return historico[-1]
