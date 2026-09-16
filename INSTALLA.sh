#!/usr/bin/env bash
# =============================================================
# Photocarcifo - Installazione con un solo comando
# Eseguire come root sul container Ubuntu (192.168.1.206):
#
#     sudo bash INSTALLA.sh
#
# Richiama lo script completo in deploy/install.sh.
# =============================================================
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$DIR/deploy/install.sh"
exec bash "$DIR/deploy/install.sh"
