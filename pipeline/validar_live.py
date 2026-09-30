# -*- coding: utf-8 -*-
"""
Checagem de sanidade do live.json antes de publicar. Compara a versao recem
gerada com a ultima versao publicada (HEAD do git) e recusa a publicacao se
encontrar sinais de dado quebrado/corrompido - por exemplo, votos ou secoes
apuradas que DIMINUIRAM em vez de aumentar (apuracao e monotonica: o numero
so cresce ao longo do dia). Isso existe para nunca publicar um numero errado
sem que uma pessoa confirme que e intencional.
"""
import json


class GitIndisponivel(Exception):
    """git nao respondeu a tempo - diferente de 'nao existe versao publicada ainda'.
    Nesse caso e mais seguro RECUSAR a publicacao do que seguir sem checar."""


def _scope_stats_flat(bundle):
    """{(cargo, scope): {ts,st,vv,...}}"""
    out = {}
    for cargo, por_scope in (bundle.get("scopeStats") or {}).items():
        for scope, stats in por_scope.items():
            out[(cargo, scope)] = stats
    return out


def validar(old_bundle, new_bundle):
    """Retorna lista de problemas encontrados (vazia = tudo ok)."""
    problemas = []

    if not new_bundle.get("scopeStats"):
        problemas.append("live.json novo nao tem 'scopeStats' - parece vazio ou malformado.")
        return problemas

    if old_bundle is None:
        return problemas  # primeira publicacao, nao ha o que comparar

    old_cargos = set(old_bundle.get("scopeStats", {}).keys())
    new_cargos = set(new_bundle.get("scopeStats", {}).keys())
    sumidos = old_cargos - new_cargos
    if sumidos:
        problemas.append("Cargo(s) que existiam e desapareceram: %s" % ", ".join(sorted(sumidos)))

    old_flat = _scope_stats_flat(old_bundle)
    new_flat = _scope_stats_flat(new_bundle)

    for (cargo, scope), old_s in old_flat.items():
        new_s = new_flat.get((cargo, scope))
        if new_s is None:
            problemas.append("%s/%s existia e sumiu da nova versao." % (cargo, scope))
            continue
        if new_s.get("st", 0) < old_s.get("st", 0):
            problemas.append(
                "%s/%s: secoes apuradas CAIU (%s -> %s)" % (cargo, scope, old_s.get("st"), new_s.get("st"))
            )
        if new_s.get("vv", 0) < old_s.get("vv", 0):
            problemas.append(
                "%s/%s: votos validos CAIU (%s -> %s)" % (cargo, scope, old_s.get("vv"), new_s.get("vv"))
            )
        pst = new_s.get("pst", 0)
        if pst < 0 or pst > 100:
            problemas.append("%s/%s: %% apurado fora da faixa 0-100 (%s)" % (cargo, scope, pst))

    old_vv_total = sum(s.get("vv", 0) for s in old_flat.values())
    new_vv_total = sum(s.get("vv", 0) for s in new_flat.values())
    if new_vv_total < old_vv_total:
        problemas.append(
            "Total geral de votos validos CAIU (%d -> %d) - forte indicio de dado incompleto." % (old_vv_total, new_vv_total)
        )

    return problemas


def apenas_quedas(problemas):
    """True se TODOS os problemas sao numero que CAIU (secoes/votos) - o
    tipo que uma correcao do proprio TSE produz. Arquivo quebrado (cargo ou
    UF sumiu, scopeStats vazio, % fora de 0-100) nunca entra aqui: isso o
    update.py jamais libera sozinho."""
    return bool(problemas) and all("CAIU" in p for p in problemas)


def carregar_live_publicado(site_dir, timeout=15):
    """Le o live.json que esta publicado agora (HEAD do git), ou None se nao existir
    ainda (primeira publicacao - nada pra comparar, tudo bem seguir sem checagem).
    Se o git nao responder em `timeout`s, levanta GitIndisponivel em vez de devolver
    None - travar/nao responder e um estado ambiguo, e mais seguro recusar a
    publicacao do que assumir silenciosamente que "nao ha versao anterior"."""
    import subprocess
    try:
        r = subprocess.run(["git", "show", "HEAD:live.json"], cwd=site_dir,
                            capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GitIndisponivel("'git show HEAD:live.json' nao respondeu em %ds" % timeout)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None
