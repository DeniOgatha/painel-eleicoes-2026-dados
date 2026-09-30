# -*- coding: utf-8 -*-
"""
Publica live.json/historico*.json num repositorio GitHub PUBLICO e SEPARADO
do codigo do site (que continua privado). Cada pagina em site/*.html busca os
dados direto de raw.githubusercontent.com desse repo (ver DATA_BASE em cada
.html) em vez de buscar do proprio Netlify.

Por que: raw.githubusercontent.com libera CORS e nao envolve build/deploy
nenhum - so um "git push" comum. O Netlify entao so precisa reconstruir o
site quando o HTML/JS realmente muda (raro, feito na mao), nunca a cada
atualizacao de dado (isso ja seria 1 deploy por ciclo, 20s em 20s - o plano
gratuito atual do Netlify cobra por deploy e esgotaria em minutos).

CONFIGURACAO (uma vez so, feita por uma pessoa):
  1) crie um repositorio PUBLICO e VAZIO no GitHub (sem README/gitignore/
     license) - por exemplo "painel-eleicoes-2026-dados" na mesma conta do
     repo do site.
  2) preencha "dados_publicos_repo" em config.json com a URL https:// dele.
  3) rode:  python publicar_dados.py --configurar
     (clona o repo vazio para dados_publicos/ - so acontece uma vez)
  4) se a URL usada no passo 1 tiver dono/nome diferentes de
     "DeniOgatha/painel-eleicoes-2026-dados", ajuste o raw.githubusercontent.com
     hardcoded no DATA_BASE de cada site/*.html.

Dai em diante o update.py chama publicar() sozinho a cada ciclo com dado novo.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DADOS_DIR = os.path.join(HERE, "dados_publicos")
CONFIG_PATH = os.path.join(HERE, "config.json")
ARQUIVOS = ["live.json", "historico.json", "historico-clausula.json", "status.json"]


class NaoConfigurado(Exception):
    """dados_publicos/ ainda nao foi clonado - ver instrucoes no topo deste arquivo."""


class GitIndisponivel(Exception):
    """git nao respondeu a tempo - mais seguro recusar a publicacao do que
    seguir sem checar contra a versao publicada."""


def _url_repo():
    try:
        cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    return (cfg.get("dados_publicos_repo") or "").strip()


def _run_git(args, cwd, timeout):
    print(">", " ".join(["git"] + args))
    try:
        return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        print("ATENCAO: 'git %s' nao respondeu em %ds - desistindo." % (" ".join(args), timeout))
        return None


def configurado():
    return os.path.isdir(os.path.join(DADOS_DIR, ".git"))


def sincronizar():
    """Traz o que ja esta publicado (git pull). Desde 2026-09-30 dois lugares
    podem publicar no repo de dados - este PC (EXECUTAR\3 - Piloto automatico) e o
    GitHub Actions (.github/workflows/apuracao.yml no proprio repo de dados) -
    entao cada ciclo comeca alinhado com o outro. "-X theirs" no rebase =
    em conflito, fica o commit LOCAL (o mais novo deste ciclo)."""
    if not configurado():
        return False
    r = _run_git(["pull", "--rebase", "-X", "theirs"], DADOS_DIR, timeout=45)
    if r is None or r.returncode != 0:
        _run_git(["rebase", "--abort"], DADOS_DIR, timeout=15)
        print("ATENCAO: 'git pull' no repo de dados falhou (%s) - segue com a copia local." %
              (((r.stderr or r.stdout or "").strip()[:200]) if r else "sem resposta"))
        return False
    return True


def _push():
    """git push; se o outro lado (PC/nuvem) publicou no meio, sincroniza e tenta de novo."""
    push = _run_git(["push"], DADOS_DIR, timeout=45)
    if push is not None and push.returncode == 0:
        return push
    if sincronizar():
        push = _run_git(["push"], DADOS_DIR, timeout=45)
    return push


def configurar():
    """Clona o repo publico (ja deve existir, vazio, no GitHub) para
    dados_publicos/. Rodar uma unica vez, manualmente."""
    url = _url_repo()
    if not url:
        print("Defina 'dados_publicos_repo' em config.json primeiro (URL https:// do repo publico vazio).")
        return 1
    if configurado():
        print("%s ja existe - nada a fazer." % os.path.relpath(DADOS_DIR, HERE))
        return 0
    r = subprocess.run(["git", "clone", url, DADOS_DIR], cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print((r.stdout or "") + (r.stderr or ""))
    if r.returncode != 0:
        return 1
    print("Configurado: %s -> %s" % (url, os.path.relpath(DADOS_DIR, HERE)))
    print("update.py ja pode publicar dados aqui a cada ciclo com novidade do TSE.")
    return 0


def carregar_publicado():
    """Le o live.json publicado agora (HEAD do repo de dados), ou None se
    ainda nao existe nenhuma publicacao (primeira vez)."""
    if not configurado():
        raise NaoConfigurado("dados_publicos/ ainda nao foi configurado (rode --configurar, ver topo deste arquivo).")
    try:
        # encoding explicito: sem ele o Windows decodifica em cp1252 e quebra em
        # nome com acento (ex. "Á" = bytes C3 81; 0x81 nao existe em cp1252).
        r = subprocess.run(["git", "show", "HEAD:live.json"], cwd=DADOS_DIR, capture_output=True,
                           text=True, encoding="utf-8", timeout=15)
    except subprocess.TimeoutExpired:
        raise GitIndisponivel("'git show HEAD:live.json' em dados_publicos/ nao respondeu em 15s")
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def publicar(site_dir):
    """Copia os JSON de dados de site_dir para dados_publicos/ e da commit+push.
    Devolve True se publicou (ou nao havia nada novo pra commitar), False em
    caso de falha (fica tudo pronto pra tentar de novo no proximo ciclo)."""
    if not configurado():
        print("ATENCAO: dados_publicos/ nao configurado - rode 'python publicar_dados.py --configurar' primeiro.")
        return False

    copiados = []
    for nome in ARQUIVOS:
        origem = os.path.join(site_dir, nome)
        if os.path.isfile(origem):
            shutil.copy2(origem, os.path.join(DADOS_DIR, nome))
            copiados.append(nome)
    if not copiados:
        print("Nada pra publicar (nenhum arquivo de dados existe ainda em %s)." % site_dir)
        return True

    add = _run_git(["add"] + copiados, DADOS_DIR, timeout=30)
    if add is None or add.returncode != 0:
        print(add.stderr if add else "")
        return False

    commit = _run_git(["commit", "-m", "Atualiza dados"], DADOS_DIR, timeout=30)
    if commit is None:
        return False
    saida_commit = (commit.stdout or "") + (commit.stderr or "")
    if "nothing to commit" in saida_commit:
        return True  # copia identica a ja publicada - nao e erro, so nao havia novidade
    print(commit.stdout.strip())
    if commit.returncode != 0:
        print(commit.stderr)
        return False

    push = _push()
    if push is None or push.returncode != 0:
        print(push.stderr if push else "")
        return False
    print(push.stdout.strip())
    print("Dados publicados em %s (raw.githubusercontent.com costuma refletir em poucos minutos)." % _url_repo())
    return True


def publicar_status(site_dir):
    """Publica SO' o status.json (ultima consulta ao TSE) - a cada ciclo,
    mesmo sem dado novo, pra as paginas mostrarem que o piloto continua
    consultando. Arquivo minusculo: nao mexe no live.json (que so' e'
    publicado quando o TSE muda). Falha aqui nunca derruba o ciclo."""
    origem = os.path.join(site_dir, "status.json")
    if not configurado() or not os.path.isfile(origem):
        return False
    shutil.copy2(origem, os.path.join(DADOS_DIR, "status.json"))
    add = _run_git(["add", "status.json"], DADOS_DIR, timeout=30)
    if add is None or add.returncode != 0:
        return False
    commit = _run_git(["commit", "-m", "Status: consulta ao TSE"], DADOS_DIR, timeout=30)
    if commit is None:
        return False
    if "nothing to commit" in (commit.stdout or "") + (commit.stderr or ""):
        return True
    push = _push()
    if push is None or push.returncode != 0:
        print("ATENCAO: status.json nao publicado (%s) - tenta de novo no proximo ciclo." % ((push.stderr or "").strip() if push else "git sem resposta"))
        return False
    print("status.json publicado (ultima consulta ao TSE).")
    return True


if __name__ == "__main__":
    if "--configurar" in sys.argv:
        raise SystemExit(configurar())
    print("Uso: python publicar_dados.py --configurar")
