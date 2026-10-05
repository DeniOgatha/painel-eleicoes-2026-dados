# -*- coding: utf-8 -*-
"""
Le os arquivos de resultado unificado (EA20) baixados pelo tse_downloader.py
(pasta dados_baixados/<cargo>/<uf-ou-br>-u.json) e gera:
  - live.json: dados dinamicos (votos, % apurado, brancos/nulos/anulados,
    lista de candidatos com votos) - isso e o arquivo que deve ser
    sobrescrito e reenviado ao GitHub a cada atualizacao.

O "casco" do painel (HTML/CSS/JS) e fixo e nao precisa ser regerado a cada
atualizacao - so quando estrutura/estilo mudar.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "dados_baixados")
LIVE_OUT = os.path.join(HERE, "site", "live.json")

UF_NOMES = {
    "ac": "Acre", "al": "Alagoas", "am": "Amazonas", "ap": "Amapá", "ba": "Bahia",
    "ce": "Ceará", "df": "Distrito Federal", "es": "Espírito Santo", "go": "Goiás",
    "ma": "Maranhão", "mg": "Minas Gerais", "ms": "Mato Grosso do Sul", "mt": "Mato Grosso",
    "pa": "Pará", "pb": "Paraíba", "pe": "Pernambuco", "pi": "Piauí", "pr": "Paraná",
    "rj": "Rio de Janeiro", "rn": "Rio Grande do Norte", "ro": "Rondônia", "rr": "Roraima",
    "rs": "Rio Grande do Sul", "sc": "Santa Catarina", "se": "Sergipe", "sp": "São Paulo",
    "to": "Tocantins",
    # escopo especial do Conselheiro Distrital (0025) - unico "municipio" do
    # pais que elege esse cargo em vez de prefeito/vereador, ver CARGO_NOMES.
    "pe30015": "Fernando de Noronha",
}

CARGO_NOMES = {
    "0001": "Presidente", "0003": "Governador", "0005": "Senador",
    "0006": "Deputado Federal", "0007": "Deputado Estadual", "0008": "Deputado Distrital",
    "0025": "Conselheiro Distrital",
}

# Mesma regra/limiares usados em site/clausula-barreira.html (computar()) - mantidos
# em espelho aqui de proposito, pra gerar o retrato (snapshot) que alimenta o
# historico/tendencia. Se a regra mudar, mudar nos dois lugares.
CLAUSULA_CARGO = "0006"
CLAUSULA_LIMIAR_NACIONAL = 2.5
CLAUSULA_LIMIAR_UF = 1.5
CLAUSULA_MIN_UFS = 9
CLAUSULA_MIN_DEPUTADOS = 13

# Cargos majoritarios (1 vencedor por escopo) - mesma lista usada em
# site/novo.html (CARGOS_SEM_GRAFICO_PARTIDO). Na linha do tempo geral eles
# entram com um N pequeno (o "lider" individual e' o que importa - so' um
# vencedor por area).
CARGOS_MAJORITARIOS = {"0001", "0003", "0005"}
TIMELINE_TOP_N_MAJORITARIO = 3

# No ambiente de teste/simulacro do TSE os partidos vem com sigla generica
# "P NNNN" (sem sigla real ainda) - o NOVO nao aparece com sua sigla de
# verdade nesses dados. Pra poder testar como a aba "Candidatos NOVO" e o
# resto do painel ficam distribuidos, mapeamos manualmente o partido de teste
# abaixo pra sigla NOVO. Remover assim que os dados oficiais trouxerem a
# sigla NOVO de verdade.
SIGLA_OVERRIDE = {
    "P 9978": "NOVO",
}
SIGLA_OVERRIDE_NOME = {"NOVO": "Partido Novo"}

# Proporcionais (Dep. Federal/Estadual/Distrital, Conselheiro Distrital):
# quem e' eleito depende do quociente partidario, nao so' do voto individual,
# entao o "top N" aqui e' so' um retrato de quem esta mais votado em cada
# area - nao uma projecao de quem sera eleito. N maior que o dos majoritarios
# porque tem varias cadeiras em disputa por area, mas limitado de proposito
# pra nao inflar demais o historico.json (ver computar_timeline_snapshot).
CARGOS_PROPORCIONAIS_TIMELINE = {"0006", "0007", "0008", "0025"}
TIMELINE_TOP_N_PROPORCIONAL = 6


def computar_clausula_snapshot(scope_stats, agg_agrupamento, agrupamento_siglas):
    """Retorna um retrato pequeno (so os numeros da clausula de barreira) prontos
    para virar 1 ponto na linha do tempo. Nao inclui candidato-a-candidato nem
    nenhum outro cargo - de proposito, pra manter o historico leve."""
    stats_cargo = scope_stats.get(CLAUSULA_CARGO, {})
    agg_cargo = agg_agrupamento.get(CLAUSULA_CARGO, {})
    ufs = list(stats_cargo.keys())

    total_valido_nacional = sum(stats_cargo[uf]["vv"] for uf in ufs)
    total_secoes = sum(stats_cargo[uf]["ts"] for uf in ufs)
    total_secoes_apuradas = sum(stats_cargo[uf]["st"] for uf in ufs)

    labels = set()
    for uf in ufs:
        labels.update(agg_cargo.get(uf, {}).keys())

    linhas = []
    for label in labels:
        votos_nac, eleitos_nac, ufs15, ufs_eleito = 0, 0, 0, 0
        for uf in ufs:
            s = stats_cargo[uf]
            a = agg_cargo.get(uf, {}).get(label)
            if not a:
                continue
            votos_nac += a["votos"]
            eleitos_nac += a["eleitos"]
            pct_uf = (a["votos"] / s["vv"] * 100) if s["vv"] else 0
            if pct_uf >= CLAUSULA_LIMIAR_UF:
                ufs15 += 1
            if a["eleitos"] >= 1:
                ufs_eleito += 1
        pct_nacional = (votos_nac / total_valido_nacional * 100) if total_valido_nacional else 0
        bate_a = pct_nacional >= CLAUSULA_LIMIAR_NACIONAL and ufs15 >= CLAUSULA_MIN_UFS
        bate_b = eleitos_nac >= CLAUSULA_MIN_DEPUTADOS and ufs_eleito >= CLAUSULA_MIN_UFS
        linhas.append({
            "label": label,
            "siglas": agrupamento_siglas.get(label, [label]),
            "pct": round(pct_nacional, 4),
            "votos": votos_nac,
            "ufs15": ufs15,
            "eleitos": eleitos_nac,
            "ufsEleito": ufs_eleito,
            "bate": bool(bate_a or bate_b),
        })
    linhas.sort(key=lambda l: -l["pct"])

    return {
        "pstNacional": round(total_secoes_apuradas / total_secoes * 100, 2) if total_secoes else 0.0,
        "totalValidoNacional": total_valido_nacional,
        "linhas": linhas,
    }


def computar_timeline_snapshot(scope_stats, cand_rows, partido_list, cargos_presentes):
    """Retorna um retrato pequeno pra virar 1 ponto na linha do tempo geral:
    % apurado nacional de CADA cargo, e o top N mais votados de cada escopo
    (N menor pros majoritarios, maior pros proporcionais - ver
    TIMELINE_TOP_N_MAJORITARIO/TIMELINE_TOP_N_PROPORCIONAL). De proposito bem
    mais enxuto que o live.json inteiro - e' isso que fica guardado em
    historico.json a cada rodada com dado novo."""
    apuracao = {}
    for cargo_cod in cargos_presentes:
        stats_cargo = scope_stats.get(cargo_cod, {})
        ts = sum(s["ts"] for s in stats_cargo.values())
        st = sum(s["st"] for s in stats_cargo.values())
        apuracao[cargo_cod] = round(st / ts * 100, 2) if ts else 0.0

    lideranca = {}
    for cargo_cod in cargos_presentes:
        if cargo_cod in CARGOS_MAJORITARIOS:
            top_n = TIMELINE_TOP_N_MAJORITARIO
        elif cargo_cod in CARGOS_PROPORCIONAIS_TIMELINE:
            top_n = TIMELINE_TOP_N_PROPORCIONAL
        else:
            continue
        stats_cargo = scope_stats.get(cargo_cod, {})
        por_scope = {}
        for scope, p_idx, nmu, num, vap, elt, sqcand, st in cand_rows.get(cargo_cod, []):
            por_scope.setdefault(scope, []).append((vap, nmu, num, p_idx))
        lideranca[cargo_cod] = {}
        for scope, cands in por_scope.items():
            cands.sort(key=lambda c: -c[0])
            vv = stats_cargo.get(scope, {}).get("vv") or 0
            lideranca[cargo_cod][scope] = [
                {
                    "nm": nmu, "num": num, "sg": partido_list[p_idx] if 0 <= p_idx < len(partido_list) else "?",
                    "vap": vap, "pvap": round(vap / vv * 100, 2) if vv else 0.0,
                }
                for vap, nmu, num, p_idx in cands[:top_n]
            ]

    return {"apuracao": apuracao, "lideranca": lideranca}


def i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def f(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def main():
    partido_nomes = {}
    partido_dict, partido_list = {}, []
    partido_total_geral = {}

    scope_stats = {}          # cargo -> scope -> {ts,st,pst,tv,vv,vb,vn,vanul,te,c,pc,a,pa}
    agg_partido = {}          # cargo -> scope -> sigla -> {votos,cand,eleitos}
    # agrupamento = unidade eleitoral real (partido isolado OU federação de partidos).
    # Essencial para a clausula de barreira: uma federacao vale pelos votos somados
    # de todos os partidos que a compoem, nao pelos partidos isoladamente.
    agg_agrupamento = {}       # cargo -> scope -> label -> {votos,cand,eleitos,siglas:[...]}
    agrupamento_siglas = {}    # label -> set de siglas (para exibir "PT + PC do B")
    cand_rows = {}            # cargo -> [[scope, partido_idx, nmu, num, vap, elt, sqcand, st], ...]
    # dg/hg (data/hora de geracao) do TSE: o MAIS RECENTE entre todos os
    # arquivos. Era o do 1o arquivo lido (Presidente/br) - em 04/10 o TSE parou
    # de regerar o de Presidente as 18:48 e seguiu nos estados, entao o update.py
    # achava que nao tinha dado novo e nao publicava mais nada.
    fonte_dg_hg = {}
    fonte_chave = None
    # Assinatura do conteudo baixado (cargo, area, dg/hg, idg, secoes
    # totalizadas de cada arquivo): o TSE regera arquivo com mais secoes
    # mantendo um dg/hg ANTERIOR ao maior ja' visto (04/10: Dep. Federal SP foi
    # de 84% a 88% com hg 19:31:13, abaixo do 19:32:39 de outra UF), entao so'
    # o horario nao basta pra saber se ha dado novo - ver update.py.
    assinatura_partes = []

    if not os.path.isdir(SRC):
        print("Pasta de dados baixados nao encontrada:", SRC)
        print("Rode antes: python tse_downloader.py --update  (ou mock_data.py para teste)")
        return 1

    foto_base_por_cargo = {}
    origem_path = os.path.join(SRC, "_origem.json")
    if os.path.isfile(origem_path):
        origem = json.load(open(origem_path, encoding="utf-8"))
        foto_base_por_cargo = origem.get("fotoBasePorCargo", {})

    # "acompanhamento" e "config" sao pastas auxiliares do tse_downloader.py
    # (EA14/15 e EA12), nao cargos - excluir daqui pra nao virarem "cargos"
    # vazios no live.json.
    NAO_CARGO = {"acompanhamento", "config"}
    cargos_presentes = sorted(
        d for d in os.listdir(SRC)
        if os.path.isdir(os.path.join(SRC, d)) and d not in NAO_CARGO
    )
    for cargo_cod in cargos_presentes:
        cargo_dir = os.path.join(SRC, cargo_cod)
        scope_stats.setdefault(cargo_cod, {})
        agg_partido.setdefault(cargo_cod, {})
        agg_agrupamento.setdefault(cargo_cod, {})
        cand_rows.setdefault(cargo_cod, [])

        for fname in sorted(os.listdir(cargo_dir)):
            if not fname.endswith("-u.json"):
                continue
            scope = fname.replace("-u.json", "")
            d = json.load(open(os.path.join(cargo_dir, fname), encoding="utf-8"))

            if d.get("dg") and d.get("hg"):
                try:
                    dd, mm, yy = d["dg"].split("/")
                    chave = (yy, mm, dd, d["hg"])
                except ValueError:
                    chave = None
                if chave and (fonte_chave is None or chave > fonte_chave):
                    fonte_chave = chave
                    fonte_dg_hg = {"dg": d.get("dg"), "hg": d.get("hg")}

            s, e, v = d.get("s", {}), d.get("e", {}), d.get("v", {})
            assinatura_partes.append("%s|%s|%s|%s|%s|%s" % (cargo_cod, scope, d.get("dg"), d.get("hg"), d.get("idg"), s.get("st")))
            ts, st = i(s.get("ts")), i(s.get("st"))
            te, comp, absten = i(e.get("te")), i(e.get("c")), i(e.get("a"))
            tv, vv, vb, vn = i(v.get("tv")), i(v.get("vv")), i(v.get("vb")), i(v.get("vn"))
            # Majoritarios (Presidente/Governador/Senador): o TSE calcula o % de
            # cada candidato - e decide 1o/2o turno - sobre os validos
            # COMPUTADOS (vvc = validos + anulados sub judice), nao sobre "vv".
            # 04/10: Governador RJ com Garotinho sub judice - sobre vv o painel
            # dava 50,8% pro 1o colocado, o TSE 49,27% e 2o turno. Proporcionais
            # seguem com vv (base da clausula de desempenho).
            if cargo_cod in ("0001", "0003", "0005") and v.get("vvc"):
                vv = i(v.get("vvc"))
            vanul = i(v.get("van")) + i(v.get("vansj"))

            scope_stats[cargo_cod][scope] = {
                "ts": ts, "st": st, "pst": round(st / ts * 100, 2) if ts else 0.0,
                "tv": tv, "vv": vv, "vb": vb, "vn": vn, "vanul": vanul,
                "te": te, "c": comp, "pc": round(comp / te * 100, 2) if te else 0.0,
                "a": absten, "pa": round(absten / te * 100, 2) if te else 0.0,
                # tf = "totalizacao final" (EA20): o juiz eleitoral encerrou a
                # eleicao nessa abrangencia. 100% das urnas apuradas (st == ts)
                # ainda NAO e' isso - ver clausula-barreira.html (fases).
                "tf": 1 if d.get("tf") == "s" else 0,
                # md = "matematicamente definido" (EA20, so' Presidente e
                # Governador, so' enquanto tf=n): "e" eleito, "s" segundo
                # turno garantido, "n"/ausente nao definido. E' o que deixa o
                # painel anunciar o resultado antes da totalizacao final.
                "md": (d.get("md") or "").strip().lower() if d.get("tf") != "s" else "",
            }

            for cg in d.get("carg", []):
                for agr in cg.get("agr", []):
                    agr_label = agr.get("nm") or agr.get("com") or "?"
                    agr_votos, agr_cand, agr_eleitos = 0, 0, 0
                    agr_siglas = []

                    for par in agr.get("par", []):
                        # EA20 (TSE, versao 2026-07-10): partido "inapto" vem
                        # com 2 asteriscos colados na sigla ("XYZ**") - tira pra
                        # nao virar um partido separado do mesmo "XYZ" em
                        # outra UF/cargo.
                        sg = (par.get("sg") or "").rstrip("*").strip() or "S/PARTIDO"
                        sg = SIGLA_OVERRIDE.get(sg, sg)
                        if sg not in partido_dict:
                            partido_dict[sg] = len(partido_list)
                            partido_list.append(sg)
                        p_idx = partido_dict[sg]
                        partido_nomes[sg] = SIGLA_OVERRIDE_NOME.get(sg) or partido_nomes.get(sg) or par.get("nm") or sg

                        # So' voto VALIDO conta (e' a base da clausula de
                        # desempenho): tvtn = validos nominais, tvtl = validos de
                        # legenda. tvan/tval/vap sao votos "computados", que
                        # incluem os anulados e os anulados sub judice (dvt) -
                        # nunca usar esses como total do partido. Se o TSE nao
                        # mandar tvtn, soma so' os candidatos com dvt "Valido".
                        cand_list = par.get("cand", [])
                        if par.get("tvtn") is not None:
                            nominal = i(par.get("tvtn"))
                        else:
                            nominal = sum(i(c.get("vap")) for c in cand_list
                                          if (c.get("dvt") or "").lower().startswith("v"))
                        legenda = i(par.get("tvtl"))
                        total_partido = nominal + legenda
                        n_eleitos = sum(1 for c in cand_list if c.get("e") == "s")

                        pacc = agg_partido[cargo_cod].setdefault(scope, {}).setdefault(
                            sg, {"votos": 0, "cand": 0, "eleitos": 0, "legenda": 0}
                        )
                        pacc["votos"] += total_partido
                        # so' os de legenda (voto so' no numero do partido) -
                        # site/novo.html mostra como uma linha a parte
                        pacc["legenda"] += legenda
                        pacc["cand"] += len(cand_list)
                        pacc["eleitos"] += n_eleitos
                        partido_total_geral[sg] = partido_total_geral.get(sg, 0) + total_partido

                        agr_votos += total_partido
                        agr_cand += len(cand_list)
                        agr_eleitos += n_eleitos
                        agr_siglas.append(sg)

                        for c in cand_list:
                            nmu = (c.get("nmu") or c.get("nm") or "").replace("\t", " ").replace("\n", " ")
                            num = (c.get("n") or "").replace("\t", "")
                            vap = i(c.get("vap"))
                            elt = 1 if c.get("e") == "s" else 0
                            sqcand = (c.get("sqcand") or "").replace("\t", "")
                            # "st" = situacao real do TSE p/ candidato ("Eleito por QP",
                            # "Eleito por media", "Suplente", "Nao eleito", ou vazio antes
                            # da apuracao definir) - vem pronta do arquivo, so' passamos
                            # adiante (ver site/novo.html e site/candidatos.html).
                            st = (c.get("st") or "").replace("\t", " ").replace("\n", " ")
                            cand_rows[cargo_cod].append([scope, p_idx, nmu, num, vap, elt, sqcand, st])

                    aacc = agg_agrupamento[cargo_cod].setdefault(scope, {}).setdefault(
                        agr_label, {"votos": 0, "cand": 0, "eleitos": 0, "vag": 0}
                    )
                    aacc["votos"] += agr_votos
                    aacc["cand"] += agr_cand
                    aacc["eleitos"] += agr_eleitos
                    # vag (EA20, so' cargo proporcional): cadeiras que o TSE ja'
                    # atribui a federacao/partido isolado nesta totalizacao
                    # (quociente + sobras). Existe ANTES dos nomes dos eleitos,
                    # que so' saem na totalizacao final - e' o que o painel usa
                    # pra montar o hemiciclo da Camara durante a apuracao.
                    aacc["vag"] += i(agr.get("vag"))
                    agrupamento_siglas.setdefault(agr_label, set()).update(agr_siglas)

    top8 = [sg for sg, _ in sorted(partido_total_geral.items(), key=lambda kv: -kv[1])[:8]]

    cand_txt = {}
    for cargo_cod, rows in cand_rows.items():
        parts = []
        cur_scope = None
        for scope, p_idx, nmu, num, vap, elt, sqcand, st in rows:
            if scope != cur_scope:
                parts.append("#" + scope)
                cur_scope = scope
            parts.append(str(p_idx) + "\t" + nmu + "\t" + num + "\t" + str(vap) + "\t" + str(elt) + "\t" + sqcand + "\t" + st)
        cand_txt[cargo_cod] = "\n".join(parts)

    agrupamento_siglas_out = {label: sorted(siglas) for label, siglas in agrupamento_siglas.items()}

    # Na clausula de desempenho a federacao conta como UM partido, somando
    # todas as UFs pelo nome (label) do agrupamento. Se o mesmo partido
    # aparecer sob dois labels em Dep. Federal (ex.: nome da federacao grafado
    # diferente em alguma UF), os votos dele ficariam divididos e o calculo
    # sairia errado - avisa alto em vez de seguir calado.
    labels_por_sigla = {}
    for por_label in agg_agrupamento.get(CLAUSULA_CARGO, {}).values():
        for label in por_label:
            for sg in agrupamento_siglas.get(label, ()):
                labels_por_sigla.setdefault(sg, set()).add(label)
    for sg, labels in sorted(labels_por_sigla.items()):
        if len(labels) > 1:
            print("ATENCAO (clausula): partido %s aparece em %d agrupamentos diferentes em Dep. Federal: %s"
                  % (sg, len(labels), " | ".join(sorted(labels))))

    gerado_em = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    clausula_snapshot = computar_clausula_snapshot(scope_stats, agg_agrupamento, agrupamento_siglas_out)
    clausula_snapshot["geradoEm"] = gerado_em

    timeline_snapshot = computar_timeline_snapshot(scope_stats, cand_rows, partido_list, cargos_presentes)
    timeline_snapshot["fonteAssinatura"] = hashlib.sha1(chr(10).join(sorted(assinatura_partes)).encode("utf-8")).hexdigest()[:16]
    timeline_snapshot["geradoEm"] = gerado_em
    timeline_snapshot["fonteDg"] = fonte_dg_hg.get("dg")
    timeline_snapshot["fonteHg"] = fonte_dg_hg.get("hg")

    bundle = {
        "meta": {
            "geradoEm": gerado_em,
            "fonte": "dados_baixados (ver tse_downloader.py)",
        },
        "ufNomes": UF_NOMES,
        "cargoNomes": CARGO_NOMES,
        "partidoNomes": partido_nomes,
        "partidoList": partido_list,
        "top8": top8,
        "scopeStats": scope_stats,
        "aggPartido": agg_partido,
        "aggAgrupamento": agg_agrupamento,
        "agrupamentoSiglas": agrupamento_siglas_out,
        "fotoBasePorCargo": foto_base_por_cargo,
        "candTxt": cand_txt,
        "clausulaSnapshot": clausula_snapshot,
        "timelineSnapshot": timeline_snapshot,
    }

    os.makedirs(os.path.dirname(LIVE_OUT), exist_ok=True)
    with open(LIVE_OUT, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, ensure_ascii=False, separators=(",", ":"))

    print("live.json gerado em:", LIVE_OUT, "(%.2f MB)" % (os.path.getsize(LIVE_OUT) / 1e6))
    for cargo_cod in cargos_presentes:
        n = len(cand_rows.get(cargo_cod, []))
        print("  ", CARGO_NOMES.get(cargo_cod, cargo_cod), "-", n, "candidatos,",
              len(scope_stats.get(cargo_cod, {})), "areas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
