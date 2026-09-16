#!/usr/bin/env bash
# Genera un documento con il codice sorgente completo del progetto.
cd /opt/photocarcifo
OUT=docs/CODICE.md
{
  echo "# PHOTOCARCIFO — Codice sorgente completo"
  echo ""
  echo "Generato il $(date '+%d/%m/%Y alle %H:%M')."
  echo "Accompagna \`PHOTOCARCIFO.md\`, che spiega architettura e procedure."
  echo ""
  echo "---"
  echo ""
  echo "## Indice"
  echo ""
  for f in app/*.py app/routers/*.py; do
    [ -f "$f" ] && echo "- \`$f\`"
  done
  for f in app/templates/*.html app/templates/*/*.html; do
    [ -f "$f" ] && echo "- \`$f\`"
  done
  for f in app/static/css/*.css app/static/js/*.js; do
    [ -f "$f" ] && echo "- \`$f\`"
  done
  echo "- configurazioni di sistema"
  echo ""
  echo "---"
  echo ""
  echo "## Python"
  echo ""
  # Elenco preso dalla cartella, non scritto a mano. La versione
  # precedente nominava i file uno per uno e si era fermata a quelli di
  # allora: dieci moduli su trenta — fra cui le traduzioni, la ricerca per
  # numero e la lettura automatica — comparivano nell'indice ma il loro
  # codice non c'era. Chi leggeva il documento si faceva un'idea sbagliata
  # di cosa fa il sito, ed e' peggio che non avere documentazione.
  for f in app/*.py; do
    [ "$(basename "$f")" = "__init__.py" ] && continue
    if [ -f "$f" ]; then
      echo "### \`$f\`"; echo ""; echo '```python'; cat "$f"; echo '```'; echo ""
    fi
  done
  echo "## Controlli automatici"
  echo ""
  for f in tests/*.py; do
    if [ -f "$f" ]; then
      echo "### \`$f\`"; echo ""; echo '```python'; cat "$f"; echo '```'; echo ""
    fi
  done
  echo "## Rotte"
  echo ""
  for f in app/routers/*.py; do
    [ "$(basename "$f")" = "__init__.py" ] && continue
    echo "### \`$f\`"; echo ""; echo '```python'; cat "$f"; echo '```'; echo ""
  done
  echo "## Pagine"
  echo ""
  for f in app/templates/base.html app/templates/public/*.html \
           app/templates/admin/*.html app/templates/errors/*.html; do
    if [ -f "$f" ]; then
      echo "### \`$f\`"; echo ""; echo '```html'; cat "$f"; echo '```'; echo ""
    fi
  done
  echo "## Stile"
  echo ""
  echo "### \`app/static/css/style.css\`"; echo ""; echo '```css'
  cat app/static/css/style.css; echo '```'; echo ""
  echo "## JavaScript"
  echo ""
  for f in app/static/js/*.js; do
    echo "### \`$f\`"; echo ""; echo '```javascript'; cat "$f"; echo '```'; echo ""
  done
  echo "## Configurazioni di sistema"
  echo ""
  for f in /etc/nginx/sites-available/photocarcifo \
           /etc/nginx/sites-available/meteo \
           /etc/nginx/sites-available/000-default-catchall; do
    if [ -f "$f" ]; then
      echo "### \`$f\`"; echo ""; echo '```nginx'; cat "$f"; echo '```'; echo ""
    fi
  done
  for f in /etc/systemd/system/photocarcifo*.service /etc/systemd/system/photocarcifo*.timer; do
    if [ -f "$f" ]; then
      echo "### \`$f\`"; echo ""; echo '```ini'; cat "$f"; echo '```'; echo ""
    fi
  done
  for f in /usr/local/bin/photocarcifo-*.sh /usr/local/bin/photocarcifo-*.py; do
    if [ -f "$f" ]; then
      echo "### \`$f\`"; echo ""; echo '```bash'; cat "$f"; echo '```'; echo ""
    fi
  done
  echo "## Struttura del database"
  echo ""
  echo '```sql'
  sqlite3 data/photocarcifo.db ".schema"
  echo '```'
  echo ""
  echo "## Configurazione"
  echo ""
  echo "Contenuto di \`.env\` con i valori riservati oscurati:"
  echo ""
  echo '```'
  sed -E 's/(SECRET_KEY|PASSWORD|TOKEN)=.*/\1=***nascosto***/' .env
  echo '```'
} > "$OUT"
echo "Creato $OUT"
wc -l "$OUT"
du -h "$OUT"
