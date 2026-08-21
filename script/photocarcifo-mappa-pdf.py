#!/usr/bin/env python3
"""Converte la mappa del sito in PDF, leggibile da telefono."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as cv

SORGENTE = Path("/opt/photocarcifo/MAPPA/MAPPA.txt")
DESTINAZIONE = Path("/opt/photocarcifo/MAPPA/Photocarcifo-Mappa.pdf")

BLU = colors.HexColor("#2b4bff")
INK = colors.HexColor("#0a0c14")
SOFT = colors.HexColor("#5b6070")
W, H = A5
MARGINE = 12 * mm
INTERLINEA = 3.3 * mm


def pulisci(riga: str) -> str:
    """Toglie le cornici a caratteri, che in PDF non servono."""
    for c in "╔╗╚╝║═╠╣╦╩╬─│┌┐└┘":
        riga = riga.replace(c, "")
    return riga.rstrip()


def main() -> int:
    if not SORGENTE.exists():
        print("mappa non trovata")
        return 1

    c = cv.Canvas(str(DESTINAZIONE), pagesize=A5)
    c.setTitle("Photocarcifo - Mappa del sito")
    y = H - MARGINE - 6 * mm

    def intestazione():
        c.setFillColor(BLU)
        c.rect(0, H - 5 * mm, W, 5 * mm, stroke=0, fill=1)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(SOFT)
        c.drawString(MARGINE, 7 * mm, "PHOTOCARCIFO - mappa del sito")
        c.drawRightString(W - MARGINE, 7 * mm, str(c.getPageNumber()))

    intestazione()

    for grezza in SORGENTE.read_text(encoding="utf-8").splitlines():
        riga = pulisci(grezza)
        if not riga.strip():
            y -= INTERLINEA * 0.6
            continue

        nudo = riga.strip()
        if nudo.isupper() and len(nudo) < 45 and not nudo.startswith(("app/", "/", ">")):
            y -= INTERLINEA * 0.8
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(BLU)
        elif nudo.startswith(("app/", "data/", "backup/", "/etc/", "/usr/",
                              "/mnt/", "MAPPA/", ".env")):
            c.setFont("Courier-Bold", 7)
            c.setFillColor(INK)
        elif nudo.startswith(("COSA FA", "LEGATO A", "COMANDO")):
            c.setFont("Helvetica", 6.8)
            c.setFillColor(SOFT)
        else:
            c.setFont("Helvetica", 7)
            c.setFillColor(INK)

        if y < MARGINE + 8 * mm:
            c.showPage()
            intestazione()
            y = H - MARGINE - 6 * mm

        c.drawString(MARGINE, y, riga[:96])
        y -= INTERLINEA

    c.showPage()
    c.save()
    print("creato:", DESTINAZIONE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
