# -*- coding: utf-8 -*-
"""
Downloader dos arquivos de divulgacao de resultados do TSE (Eleicoes 2026),
seguindo a especificacao do documento "Instrucoes para download dos arquivos
da Divulgacao de resultados das Eleicoes 2026" (TSE, v1.0, 25/05/2026).

ATUALIZADO em 2026-09-15: config.json aponta para o ambiente de SIMULADO,
com parametros OFICIAIS confirmados pelo TSE (pagina de simulados, aba
Documentos) - nao e mais palpite:
  host=resultados-sim.tse.jus.br/simulado, ambiente=simulado2026,
  ciclo=ele2026, pleito=17801, eleicoes: 21270=Federal (Presidente),
  21272=Estadual (Governador/Senador/DepFederal/DepEstadual/DepDistrital),
  21274=Municipal (Conselheiro Distrital, so' DF). Confirmado por request
  real (HTTP 200) em 2026-09-15 contra ele-c.json, uma ab.json e o
  c0001-u.json de Presidente - todos com zero votos (estado inicial do
  simulado). Janelas de teste: 15-17/set e 22-24/set/2026, 9h-12h e 14h-17h.
  O host de PRODUCAO ainda nao foi publicado pelo TSE ("sera publicado
  oportunamente") - quando sair, so trocar host/ambiente em config.json.

Uso:
  python tse_downloader.py --discover
      Busca o arquivo de configuracao de eleicoes (EA11) e imprime sua
      estrutura (util para revalidar cargos/eleicoes se o TSE mudar algo).

  python tse_downloader.py --update
      Baixa os arquivos de resultado unificado (EA20), eleitos (EA10),
      acompanhamento (EA14/EA15) e config de municipios (EA12, um por
      eleicao distinta) para os cargos configurados em config.json,
      salvando em <saida_dir>/. Ciclo e mapa cargo->eleicao vem de
      config.json por padrao (pode sobrescrever com --ciclo/--eleicoes-json).
      Baixa em paralelo (--concorrencia, padrao 10 simultaneas - o limite
      oficial do TSE e 100 req/s por IP, confirmado na pagina de simulados;
      ficamos bem abaixo disso de proposito).
"""
import json
import os
import sys
import time
import argparse
import threading
import concurrent.futures
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

# Limite oficial do TSE (confirmado em tse.jus.br/eleicoes/informacoes-tecnicas-
# sobre-a-divulgacao-de-resultados, ago/2026): 100 requisicoes/segundo por IP,
# com bloqueio de 10min se exceder (renovado enquanto persistir). Respostas
# HTTP 304 tambem contam pro limite. Usamos so uma fracao pequena desse limite
# de proposito - o ciclo inteiro tem ~300 arquivos, entao mesmo bem abaixo do
# teto a gente termina rapido, com folga de sobra pra outros consumidores
# (imprensa etc.) batendo na mesma CDN ao mesmo tempo no dia da eleicao.
MAX_CONCORRENCIA_PADRAO = 10


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def fetch_json(url, headers, timeout=20, tentativas=3):
    """Busca uma URL e tenta interpretar como JSON. Nunca lanca excecao -
    devolve (ok, status_code_ou_None, dado_ou_texto_ou_erro). Tenta de novo
    em caso de erro de rede/timeout ou HTTP 429 (rate limit), com espera
    progressiva entre tentativas."""
    ultimo_status, ultimo_erro = None, None
    for tentativa in range(tentativas):
        if tentativa > 0:
            time.sleep(1.5 * tentativa)
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as ex:
            ultimo_erro = "erro de conexao: %s" % ex
            continue
        if resp.status_code == 429:
            ultimo_status, ultimo_erro = 429, "HTTP 429 (rate limit) - tentando de novo"
            continue
        if resp.status_code != 200:
            return False, resp.status_code, resp.text[:500]
        try:
            return True, 200, resp.json()
        except ValueError:
            return False, 200, "resposta 200 mas nao e JSON valido: %s" % resp.text[:500]
    return False, ultimo_status, ultimo_erro


def bootstrap_url(host, ambiente):
    # Estrutura documentada (secao 3 do PDF): [ambiente]/"comum"/"config"/ele-c.json
    return "https://%s/%s/comum/config/ele-c.json" % (host, ambiente)


def cmd_discover(cfg):
    headers = {"User-Agent": cfg["user_agent"]}
    url = bootstrap_url(cfg["host"], cfg["ambiente"])
    print("Buscando arquivo de configuracao de eleicoes (EA11):")
    print(" ", url)
    ok, status, data = fetch_json(url, headers)
    out_path = os.path.join(HERE, "ele-c_discover.json")
    if not ok:
        print("FALHOU. status=%s" % status)
        print("corpo/erro:", data)
        print()
        print("Isso e esperado se o TSE ainda nao publicou o ambiente 'oficial' para 2026.")
        print("Tente novamente mais perto da eleicao, ou me avise se voce tiver um")
        print("endereco/credencial especifico fornecido pelo TSE.")
        return 1

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print("OK! Resposta salva em:", out_path)
    print()
    print("Estrutura de alto nivel (chaves e tipos):")

    def describe(obj, prefix="", depth=0, max_depth=3):
        if depth > max_depth:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                t = type(v).__name__
                extra = ""
                if isinstance(v, list):
                    extra = " (lista com %d itens)" % len(v)
                print("  " * depth + prefix + str(k) + ": " + t + extra)
                if isinstance(v, (dict, list)):
                    describe(v, "", depth + 1, max_depth)
        elif isinstance(obj, list) and obj:
            describe(obj[0], "[0]. ", depth, max_depth)

    describe(data)
    print()
    print("Procure especialmente pelo atributo 'arq' (lista de tipos de arquivo")
    print("e diretorios) e por uma lista de eleicoes com seus codigos de ciclo/eleicao.")
    print("Me mande o conteudo de ele-c_discover.json para eu ajustar o parser.")
    return 0


# --- construcao de URLs conforme secoes 3 e 5 do PDF -----------------------

def fmt_cargo(cod):
    return "c" + str(cod).zfill(4)


def fmt_eleicao(cod):
    return "e" + str(cod).zfill(6)


def url_resultado_unificado_scope(host, ambiente, ciclo, eleicao, folder, prefix, cargo_cod, eleica_cod):
    # <br|uf|zz|uf+munic>-c<CCCC>-e<ELEICA>-u.json em dados/{br|uf|zz}/
    # `folder` = pasta (sempre br/uf/zz); `prefix` = prefixo do nome do arquivo
    # (igual a `folder`, exceto em escopo municipal, onde e' uf+municipio,
    # ex.: prefix="pe30015", folder="pe" - ver CARGO_CONSELHEIRO_DISTRITAL).
    fname = "%s-%s-%s-u.json" % (prefix, fmt_cargo(cargo_cod), fmt_eleicao(eleica_cod))
    return "https://%s/%s/%s/%s/dados/%s/%s" % (host, ambiente, ciclo, eleicao, folder, fname)


def url_eleitos(host, ambiente, ciclo, eleicao, folder, prefix, cargo_cod, eleica_cod):
    fname = "%s-%s-%s-e.json" % (prefix, fmt_cargo(cargo_cod), fmt_eleicao(eleica_cod))
    return "https://%s/%s/%s/%s/dados/%s/%s" % (host, ambiente, ciclo, eleicao, folder, fname)


def url_acompanhamento(host, ambiente, ciclo, eleicao, uf_ou_br, eleica_cod):
    if uf_ou_br == "br":
        fname = "br-%s-ab.json" % fmt_eleicao(eleica_cod)
    else:
        fname = "%s-%s-ab.json" % (uf_ou_br, fmt_eleicao(eleica_cod))
    return "https://%s/%s/%s/%s/dados/%s/%s" % (host, ambiente, ciclo, eleicao, uf_ou_br, fname)


def foto_base_url(host, ambiente, ciclo, eleicao):
    # secao 3 do PDF: "fotos" e irma de "dados", nao fica dentro dela.
    # arquivo final: <base>/<uf|br|zz>/<sqcand>.jpeg
    return "https://%s/%s/%s/%s/fotos/" % (host, ambiente, ciclo, eleicao)


def url_mun_config(host, ambiente, ciclo, eleicao, eleica_cod):
    # <ambiente>/<ciclo>/<cd_eleicao>/config/mun-e<ELEICA>-cm.json (EA12,
    # um arquivo por eleicao - traz cd (codigo TSE) e cdi (codigo IBGE) de
    # cada municipio, ver [[dados-tse-mapeamento-municipios]])
    fname = "mun-%s-cm.json" % fmt_eleicao(eleica_cod)
    return "https://%s/%s/%s/%s/config/%s" % (host, ambiente, ciclo, eleicao, fname)


CARGOS_NACIONAIS = {"0001"}          # Presidente: escopo "br"
CARGOS_DISTRITAL_SO_DF = {"0008"}    # Deputado Distrital: so existe no DF
CARGOS_SEM_DF = {"0007"}             # Deputado Estadual: DF nao tem (tem Distrital no lugar)

# Conselheiro Distrital (0025) e um caso especial: nao e' "distrital" do DF,
# e' o Conselho Distrital de Fernando de Noronha/PE (unico "municipio" que
# elege esse cargo em vez de prefeito/vereador - confirmado em 2026-09-15
# via mun-e021274-cm.json, que so' lista essa entrada: cd=30015, uf=pe).
CARGO_CONSELHEIRO_DISTRITAL = "0025"
UF_MUNIC_CONSELHEIRO_DISTRITAL = ("pe", "30015")


def _baixar_uma_tarefa(task, cfg, ciclo, headers, out_dir):
    tipo, cargo_cod, escopo, eleica_cod = task
    # escopo e' "uf"/"br"/"zz" normalmente, ou uma tupla (folder, prefix) nos
    # casos onde o nome do arquivo carrega mais do que a pasta (ex.: escopo
    # municipal do Conselheiro Distrital, prefix="pe30015" folder="pe").
    folder, prefix = escopo if isinstance(escopo, tuple) else (escopo, escopo)
    if tipo == "resultado":
        url = url_resultado_unificado_scope(cfg["host"], cfg["ambiente"], ciclo, eleica_cod, folder, prefix, cargo_cod, eleica_cod)
        dest = os.path.join(out_dir, cargo_cod, "%s-u.json" % prefix)
    elif tipo == "eleitos":
        url = url_eleitos(cfg["host"], cfg["ambiente"], ciclo, eleica_cod, folder, prefix, cargo_cod, eleica_cod)
        dest = os.path.join(out_dir, cargo_cod, "%s-e.json" % prefix)
    else:
        url = url_acompanhamento(cfg["host"], cfg["ambiente"], ciclo, eleica_cod, folder, eleica_cod)
        dest = os.path.join(out_dir, "acompanhamento", "%s-ab.json" % folder)

    ok, status, data = fetch_json(url, headers)
    if ok:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return True, tipo, url, None
    return False, tipo, url, status


def config_do_turno(cfg, turno):
    """2o turno (--turno 2): outra eleicao no TSE (cdt2 do ele-c.json), so'
    Presidente + Governador nas UFs que tiveram 2o turno, e pasta propria -
    o 1o turno (dados_baixados/) fica intocado. Devolve um cfg ajustado."""
    if str(turno) != "2":
        return cfg
    t2 = cfg.get("segundo_turno") or {}
    novo = dict(cfg)
    novo["eleicoes_por_cargo"] = t2["eleicoes_por_cargo"]
    novo["cargos_interesse"] = {c: n for c, n in cfg["cargos_interesse"].items() if c in t2["eleicoes_por_cargo"]}
    novo["ufs"] = t2["ufs_governador"]
    novo["saida_dir"] = t2.get("saida_dir", "dados_baixados_2t")
    return novo


def cmd_update(cfg, ciclo, eleicoes_por_cargo, concorrencia=MAX_CONCORRENCIA_PADRAO):
    """
    ciclo: string do ciclo eleitoral (ex.: "ele2026")
    eleicoes_por_cargo: dict cargo_cod -> eleica_cod (numero da eleicao daquele cargo)
    Por padrao vem de config.json (ja confirmado para o ambiente de simulado);
    passe --ciclo/--eleicoes-json so' pra sobrescrever (ex.: revalidar via --discover).

    Baixa os arquivos em paralelo (ate `concorrencia` requisicoes simultaneas).
    O limite oficial do TSE e 100 req/s por IP - o padrao aqui (10) fica bem
    abaixo disso de proposito, ver MAX_CONCORRENCIA_PADRAO acima.
    """
    headers = {"User-Agent": cfg["user_agent"]}
    out_dir = os.path.join(HERE, cfg["saida_dir"])
    os.makedirs(out_dir, exist_ok=True)

    # metadados de origem (usado pelo aggregate_2026.py para montar URLs de foto)
    foto_base_por_cargo = {
        cargo_cod: foto_base_url(cfg["host"], cfg["ambiente"], ciclo, eleica_cod)
        for cargo_cod, eleica_cod in eleicoes_por_cargo.items()
    }
    with open(os.path.join(out_dir, "_origem.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "host": cfg["host"], "ambiente": cfg["ambiente"], "ciclo": ciclo,
            "eleicoesPorCargo": eleicoes_por_cargo, "fotoBasePorCargo": foto_base_por_cargo,
        }, fh, ensure_ascii=False, indent=2)

    # config de municipios (EA12) - um por codigo de eleicao distinto usado
    config_dir = os.path.join(out_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    for eleica_cod in sorted(set(eleicoes_por_cargo.values())):
        url = url_mun_config(cfg["host"], cfg["ambiente"], ciclo, eleica_cod, eleica_cod)
        ok, status, data = fetch_json(url, headers)
        dest = os.path.join(config_dir, "mun-%s-cm.json" % fmt_eleicao(eleica_cod))
        if ok:
            with open(dest, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            print("mun-config OK:", url)
        else:
            print("mun-config FALHOU [%s] status=%s" % (url, status))

    tasks = []
    for cargo_cod in cfg["cargos_interesse"]:
        eleica_cod = eleicoes_por_cargo.get(cargo_cod)
        if eleica_cod is None:
            print("aviso: sem numero de eleicao para cargo", cargo_cod, "- pulando")
            continue
        if cargo_cod == CARGO_CONSELHEIRO_DISTRITAL:
            _uf, _munic = UF_MUNIC_CONSELHEIRO_DISTRITAL
            scopes = [(_uf, _uf + _munic)]  # folder="pe", prefix="pe30015" - so Fernando de Noronha
        elif cargo_cod in CARGOS_NACIONAIS:
            scopes = ["br"]
        elif cargo_cod in CARGOS_DISTRITAL_SO_DF:
            scopes = ["df"]
        elif cargo_cod in CARGOS_SEM_DF:
            scopes = [uf for uf in cfg["ufs"] if uf != "df"]
        else:
            scopes = cfg["ufs"]
        for escopo in scopes:
            tasks.append(("resultado", cargo_cod, escopo, eleica_cod))
            tasks.append(("eleitos", cargo_cod, escopo, eleica_cod))

    # acompanhamento: 1x BR + 1x por UF (independe do cargo)
    ref_eleica = next(iter(eleicoes_por_cargo.values()), None)
    if ref_eleica is not None:
        tasks.append(("acompanhamento", None, "br", ref_eleica))
        for uf in cfg["ufs"]:
            tasks.append(("acompanhamento", None, uf, ref_eleica))

    print("Total de arquivos a baixar:", len(tasks), "(ate %d simultaneos)" % concorrencia)
    ok_count, fail_count = 0, 0
    print_lock = threading.Lock()
    t0 = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concorrencia) as pool:
        futuros = [pool.submit(_baixar_uma_tarefa, t, cfg, ciclo, headers, out_dir) for t in tasks]
        for fut in concurrent.futures.as_completed(futuros):
            ok, tipo, url, status = fut.result()
            if ok:
                with print_lock:
                    ok_count += 1
            else:
                with print_lock:
                    fail_count += 1
                    print("falhou [%s] %s -> status=%s" % (tipo, url, status))

    print("Concluido em %.1fs: %d ok, %d falhas" % (time.time() - t0, ok_count, fail_count))
    return 0 if fail_count == 0 else 2


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--discover", action="store_true", help="Busca e inspeciona o EA11 (config de eleicoes)")
    ap.add_argument("--update", action="store_true", help="Baixa os arquivos de resultado configurados")
    ap.add_argument("--ciclo", default=None, help="Codigo do ciclo eleitoral, formato 'ele<ANO>' (default: cfg['ciclo'])")
    ap.add_argument("--eleicoes-json", default=None,
                     help="Caminho para um JSON {cargo_cod: eleica_cod} (default: cfg['eleicoes_por_cargo'])")
    ap.add_argument("--concorrencia", type=int, default=MAX_CONCORRENCIA_PADRAO,
                     help="Requisicoes simultaneas ao baixar (padrao %d - limite oficial do TSE e 100/s por IP)" % MAX_CONCORRENCIA_PADRAO)
    ap.add_argument("--turno", default="1", choices=["1", "2"],
                     help="2 = segundo turno (cfg['segundo_turno']: outra eleicao, outra pasta)")
    args = ap.parse_args()

    cfg = config_do_turno(load_config(), args.turno)

    if args.discover:
        return cmd_discover(cfg)

    if args.update:
        ciclo = args.ciclo or cfg.get("ciclo")
        if args.eleicoes_json:
            with open(args.eleicoes_json, encoding="utf-8") as fh:
                eleicoes_por_cargo = json.load(fh)
        else:
            eleicoes_por_cargo = cfg.get("eleicoes_por_cargo")
        if not ciclo or not eleicoes_por_cargo:
            print("Sem ciclo/eleicoes_por_cargo (nem em config.json, nem via --ciclo/--eleicoes-json).")
            print("Exemplo: python tse_downloader.py --update --ciclo ele2026 --eleicoes-json eleicoes.json")
            return 1
        return cmd_update(cfg, ciclo, eleicoes_por_cargo, concorrencia=args.concorrencia)

    print("Use --discover ou --update. Veja --help para detalhes.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
