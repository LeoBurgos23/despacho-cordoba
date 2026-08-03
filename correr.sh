#!/bin/bash
# =====================================================================
#  DESPACHO DIARIO — ejecutor local (plan B)
#  Corre el motor en tu Mac y publica el resultado en GitHub.
#  Lo dispara launchd de lunes a viernes; también podés correrlo
#  a mano desde la Terminal:  ~/despacho-cordoba/correr.sh
# =====================================================================

set -u

# Carpeta donde está el proyecto (ajustar si lo pusiste en otro lado)
REPO="$HOME/despacho-cordoba"
cd "$REPO" || { echo "No encuentro la carpeta $REPO"; exit 1; }

# Registro: todo lo que pase queda anotado acá
LOG="$REPO/despacho.log"
exec >> "$LOG" 2>&1
echo ""
echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="

# Claves privadas (el archivo .env NO se sube a GitHub)
if [ -f "$REPO/.env" ]; then
  set -a
  source "$REPO/.env"
  set +a
else
  echo "Falta el archivo .env con las claves. Abortando."
  exit 1
fi

# Traer lo último del repo por si editaste algo desde la web
git pull --rebase --quiet || echo "Aviso: no pude hacer git pull, sigo igual."

# Motor: descarga, analiza y guarda en docs/data
"$REPO/.venv/bin/python" "$REPO/boletin.py"
ESTADO=$?

if [ $ESTADO -ne 0 ]; then
  echo "El motor terminó con error ($ESTADO). No se publica nada."
  exit $ESTADO
fi

# Publicar los datos nuevos
mkdir -p docs/data
git add -A docs/data
if git diff --staged --quiet; then
  echo "Sin novedades para publicar."
else
  git commit -m "Despacho $(date '+%Y-%m-%d')" --quiet
  if git push --quiet; then
    echo "Publicado en GitHub."
  else
    echo "No pude publicar en GitHub (revisá la conexión o las credenciales)."
    exit 1
  fi
fi

echo "Listo."
