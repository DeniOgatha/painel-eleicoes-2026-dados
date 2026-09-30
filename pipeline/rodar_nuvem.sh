#!/usr/bin/env bash
# Loop da apuracao no GitHub Actions (ver ../.github/workflows/apuracao.yml).
# Faz o mesmo que o piloto-automatico.bat do PC: roda update.py a cada
# INTERVALO segundos ate completar HORAS_SEG. Os scripts desta pasta sao COPIA
# dos de 2026_ao_vivo/ no PC - pra atualizar, rode copiar_para_nuvem.py la.
#
# Layout no runner: a raiz do repo e' o proprio repo de dados (live.json etc.)
# e esta pasta faz o papel de 2026_ao_vivo/:
#   pipeline/dados_publicos -> ..   (publicar_dados.py publica na raiz)
#   pipeline/site/                  (live.json/historicos de trabalho)
set -u
cd "$(dirname "$0")"
ln -sfn .. dados_publicos
mkdir -p site
for f in live.json historico.json historico-clausula.json status.json; do
  [ -f "../$f" ] && cp "../$f" "site/$f"
done

INTERVALO="${INTERVALO:-60}"
FIM=$(( $(date +%s) + ${HORAS_SEG:-3600} ))
n=0
while [ "$(date +%s)" -lt "$FIM" ]; do
  n=$((n + 1))
  echo "================ ciclo $n - $(TZ=America/Sao_Paulo date '+%d/%m %H:%M:%S') (Brasilia) ================"
  # as linhas "falhou [eleitos] ... 404" sao normais ate o TSE divulgar os eleitos
  python update.py 2>&1 | grep -v '^falhou \[eleitos\]' || true
  resto=$(( FIM - $(date +%s) ))
  [ "$resto" -le 0 ] && break
  sleep $(( resto < INTERVALO ? resto : INTERVALO ))
done
echo "Fim do periodo desta execucao ($n ciclos)."
