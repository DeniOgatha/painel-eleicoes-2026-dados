# -*- coding: utf-8 -*-
"""
Comando unico de atualizacao manual do painel:
  1) baixa os arquivos mais recentes do TSE (tse_downloader.py --update)
  2) reagrega em site/live.json (aggregate_2026.py)
  3) checa sanidade (validar_live.py) - recusa publicar se votos/secoes apuradas
     tiverem CAIDO em relacao a ultima versao publicada (provavel dado quebrado)
  4) publica live.json/historico*.json no repo PUBLICO de dados (publicar_dados.py)
     - separado do codigo do site, pra pagina buscar via raw.githubusercontent.com
     sem gastar deploy no Netlify a cada atualizacao (ver publicar_dados.py)

Uso:
  python update.py --ciclo ele2026 --eleicoes-json eleicoes.json     (dados reais, quando existirem)
  python update.py --mock                                            (dados ficticios, so para teste)
  python update.py --mock --no-push                                  (gera local sem enviar ao GitHub)
  python update.py --mock --forcar                                   (publica mesmo se a checagem falhar)
  python update.py --zerado --no-push                                (candidatos reais de 2026, tudo zerado)
"""
import argparse
import datetime
import json
import subprocess
import sys
import os

import validar_live
import historico_clausula
import publicar_dados

HERE = os.path.dirname(os.path.abspath(__file__))


SITE_DIR = os.path.join(HERE, "site")

# O que aconteceu neste ciclo - usado por main() pra publicar o status.json
# mesmo quando _main() sai cedo (sem dado novo do TSE, falha no download...).
CICLO = {"consultou_tse": False, "publicou": False}
STATUS = {}

# Checagem de sanidade recusou por QUEDA de numero (validar_live.apenas_quedas)
# neste tanto de ciclos seguidos -> publica sozinho: queda que persiste ~6 min
# e' correcao do proprio TSE, nao arquivo quebrado. Sem isso a nuvem (sem
# ninguem pra rodar --forcar) ficaria travada a noite toda.
LIBERAR_APOS = 5
RETENCAO_PATH = os.path.join(SITE_DIR, "retencao.json")


def run(cmd, **kw):
    print(">", " ".join(cmd))
    return subprocess.run(cmd, cwd=HERE, **kw)


def escrever_status():
    with open(os.path.join(SITE_DIR, "status.json"), "w", encoding="utf-8") as f:
        json.dump(STATUS, f, ensure_ascii=False)


def gravar_status(ok):
    """site/status.json: quando este PC tentou baixar do TSE pela ultima vez
    e se deu certo. As paginas mostram isso como "ultima consulta ao TSE"
    (site/status-tse.js) - se o piloto parar, o horario congela."""
    STATUS.clear()
    STATUS["ultimaTentativa"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    STATUS["ok"] = bool(ok)
    escrever_status()
    CICLO["consultou_tse"] = True


def contar_retencao(problemas):
    """+1 recusa seguida (site/retencao.json); devolve quantas ja' sao."""
    try:
        r = json.load(open(RETENCAO_PATH, encoding="utf-8"))
    except (OSError, ValueError):
        r = {}
    r["vezes"] = int(r.get("vezes", 0)) + 1
    r.setdefault("desde", datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    r["motivo"] = problemas[0]
    with open(RETENCAO_PATH, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)
    return r["vezes"]


def zerar_retencao():
    if os.path.isfile(RETENCAO_PATH):
        os.remove(RETENCAO_PATH)


def trazer_publicado():
    """Antes de cada ciclo que publica: git pull no repo de dados e, se a
    linha do tempo publicada tiver mais pontos que a local (a nuvem ou outro
    PC publicou enquanto este estava parado), adota a publicada - senao este
    ciclo sobrescreveria o historico com a copia velha daqui."""
    if not publicar_dados.configurado():
        return
    publicar_dados.sincronizar()
    for nome in ("historico.json", "historico-clausula.json"):
        pub = os.path.join(publicar_dados.DADOS_DIR, nome)
        loc = os.path.join(SITE_DIR, nome)
        try:
            n_pub = len(json.load(open(pub, encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            continue
        try:
            n_loc = len(json.load(open(loc, encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            n_loc = -1
        if n_pub > n_loc:
            with open(pub, "rb") as a, open(loc, "wb") as b:
                b.write(a.read())
            print("%s: adotei a versao publicada (%d pontos, local tinha %d)." % (nome, n_pub, max(n_loc, 0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="usa dados ficticios (mock_data.py) em vez de baixar do TSE")
    ap.add_argument("--zerado", action="store_true",
                     help="usa o cadastro real de candidatos 2026 com tudo zerado (dados_zerados.py) em vez de baixar do TSE")
    ap.add_argument("--ciclo", default=None)
    ap.add_argument("--eleicoes-json", default=None)
    ap.add_argument("--no-push", action="store_true", help="nao faz git commit/push, so gera o live.json local")
    ap.add_argument("--forcar", action="store_true",
                     help="publica mesmo se a checagem de sanidade encontrar problemas (revise antes!)")
    args = ap.parse_args()
    codigo = _main(args)
    # status.json vai a cada ciclo que consultou o TSE, mesmo sem dado novo
    # (quando o live.json foi publicado, o status ja' foi junto no mesmo commit)
    if CICLO["consultou_tse"] and not CICLO["publicou"] and not args.no_push:
        publicar_dados.publicar_status(SITE_DIR)
    return codigo


def _main(args):
    py = sys.executable

    if args.mock:
        r = run([py, "mock_data.py"])
        if r.returncode != 0:
            return 1
    elif args.zerado:
        r = run([py, "dados_zerados.py"])
        if r.returncode != 0:
            return 1
    else:
        if not args.no_push:
            trazer_publicado()
        # --ciclo/--eleicoes-json sao opcionais desde 2026-09-15: se omitidos,
        # tse_downloader.py usa os valores confirmados em config.json (host do
        # simulado oficial) sem precisar rodar --discover antes.
        cmd = [py, "tse_downloader.py", "--update"]
        if args.ciclo:
            cmd += ["--ciclo", args.ciclo]
        if args.eleicoes_json:
            cmd += ["--eleicoes-json", args.eleicoes_json]
        r = run(cmd)
        gravar_status(r.returncode in (0, 2))
        if r.returncode not in (0, 2):  # 2 = concluido com algumas falhas pontuais, ainda seguimos
            return 1

    r = run([py, "aggregate_2026.py"])
    if r.returncode != 0:
        return 1

    site_dir = os.path.join(HERE, "site")
    live = json.load(open(os.path.join(site_dir, "live.json"), encoding="utf-8"))
    timeline = live.get("timelineSnapshot")
    if timeline:
        chave = (timeline.get("fonteDg"), timeline.get("fonteHg"), timeline.get("fonteAssinatura"))
        anterior = historico_clausula.ultimo_ponto(site_dir, "historico.json")
        chave_anterior = (anterior.get("fonteDg"), anterior.get("fonteHg"), anterior.get("fonteAssinatura")) if anterior else None
        if chave != chave_anterior:
            _, n_pontos = historico_clausula.apender(site_dir, timeline, nome_arquivo="historico.json")
            print("historico.json atualizado (%d pontos, fonte %s %s)" % (n_pontos, chave[0], chave[1]))
        else:
            print("historico.json: sem dado novo da fonte (%s %s) - nao apendei ponto duplicado." % chave)

    if args.no_push:
        print("`--no-push` usado: live.json atualizado localmente, nada foi enviado ao GitHub.")
        return 0

    if not publicar_dados.configurado():
        print("O repo publico de dados ainda nao foi configurado (dados_publicos/ nao existe).")
        print("Rode 'python publicar_dados.py --configurar' primeiro (ver instrucoes no topo desse arquivo).")
        return 1

    novo_bundle = live
    try:
        velho_bundle = publicar_dados.carregar_publicado()
    except publicar_dados.GitIndisponivel as ex:
        print("ATENCAO: %s - nao da pra checar a sanidade dos dados agora. Nada foi publicado." % ex)
        print("Tente de novo em instantes. Se persistir, verifique se o git nao ficou travado")
        print("(ex: arquivo dados_publicos/.git/index.lock de uma execucao anterior interrompida).")
        return 1
    # live.json ganha um meta.geradoEm novo a cada execucao, entao sem esta
    # checagem cada ciclo (20s) viraria um commit + deploy no Netlify mesmo com
    # o TSE parado. So publica quando a fonte do TSE (dg/hg) realmente mudou.
    def _fonte(bundle):
        t = (bundle or {}).get("timelineSnapshot") or {}
        # fonteAssinatura (aggregate_2026.py) muda quando qualquer arquivo do
        # TSE muda, mesmo sem dg/hg novo
        return (t.get("fonteDg"), t.get("fonteHg"), t.get("fonteAssinatura"))
    if (velho_bundle is not None and _fonte(novo_bundle)[:2] != (None, None)
            and _fonte(novo_bundle) == _fonte(velho_bundle) and not args.forcar):
        print("Sem dado novo do TSE desde a ultima publicacao (%s %s) - nada a publicar." % _fonte(novo_bundle)[:2])
        zerar_retencao()  # o publicado ja' e' o dado atual do TSE: nada retido
        return 0

    problemas = validar_live.validar(velho_bundle, novo_bundle)
    if problemas:
        print()
        print("=" * 60)
        print("CHECAGEM DE SANIDADE FALHOU")
        print("=" * 60)
        for p in problemas:
            print(" -", p)
        print()
        if not args.forcar:
            vezes = contar_retencao(problemas)
            so_quedas = validar_live.apenas_quedas(problemas)
            if so_quedas and vezes >= LIBERAR_APOS:
                print("Queda nos numeros persistiu por %d ciclos seguidos - e' o proprio TSE sustentando" % vezes)
                print("esse numero (correcao), nao arquivo quebrado. Publicando automaticamente.")
            else:
                STATUS["retida"] = True
                STATUS["motivo"] = problemas[0]
                STATUS["recusasSeguidas"] = vezes
                STATUS["liberaEmCiclos"] = (LIBERAR_APOS - vezes) if so_quedas else None
                escrever_status()
                if so_quedas:
                    print("NADA FOI PUBLICADO (%d de %d). Se a queda continuar, publica sozinho em %d ciclo(s)."
                          % (vezes, LIBERAR_APOS, LIBERAR_APOS - vezes))
                else:
                    print("NADA FOI PUBLICADO: parece arquivo quebrado - isso nunca e' liberado sozinho.")
                    print("Se for esperado, rode de novo com --forcar para publicar mesmo assim.")
                return 1
        else:
            print("--forcar usado: publicando mesmo com os problemas acima.")
        print()

    # so grava um ponto na linha do tempo da clausula de barreira APOS a checagem
    # de sanidade aprovar - nunca antes, pra nunca guardar um ponto que na
    # verdade foi rejeitado (ver historico_clausula.py).
    snapshot = novo_bundle.get("clausulaSnapshot")
    if snapshot:
        hist_path, n_pontos = historico_clausula.apender(site_dir, snapshot)
        print("historico-clausula.json atualizado (%d pontos)" % n_pontos)

    if not publicar_dados.publicar(site_dir):
        print("ATENCAO: falha ao publicar no repo de dados - nada foi publicado. Ver mensagens acima.")
        return 1
    zerar_retencao()
    CICLO["publicou"] = True
    print("Publicado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
