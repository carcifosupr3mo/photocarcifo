"""Pagina del pannello con le statistiche aggregate del sito.

Nessuna tabella nuova: legge solo cio' che scanner, tree e ricerche gia'
scrivono (node_stats, ricerche, preferiti). La dashboard principale
(admin.dashboard) mostra gia' i totali degli ultimi 30 giorni; qui sta lo
storico completo per album, utile a chi decide cosa promuovere o cosa
manca (ricerche senza risultati = foto richieste ma non trovate).
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

from ..database import get_db
from ..deps import require_admin_user
from ..templating import templates

router = APIRouter(prefix="/admin/statistiche")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def pagina(request: Request, user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        top_aperture = conn.execute(
            "SELECT n.id, n.title, n.rel_path, COUNT(*) AS quante "
            "FROM node_stats s JOIN nodes n ON n.id = s.node_id "
            "WHERE s.event='open' GROUP BY n.id ORDER BY quante DESC LIMIT 10").fetchall()
        top_download = conn.execute(
            "SELECT n.id, n.title, n.rel_path, COUNT(*) AS quante "
            "FROM node_stats s JOIN nodes n ON n.id = s.node_id "
            "WHERE s.event='download' GROUP BY n.id ORDER BY quante DESC LIMIT 10").fetchall()
        top_zip = conn.execute(
            "SELECT n.id, n.title, n.rel_path, COUNT(*) AS quante "
            "FROM node_stats s JOIN nodes n ON n.id = s.node_id "
            "WHERE s.event='zip' GROUP BY n.id ORDER BY quante DESC LIMIT 10").fetchall()
        # Andamento mensile: solo i totali per evento, non per album. E'
        # l'unico taglio temporale che node_stats sostiene bene su
        # decine di migliaia di righe senza un indice sul solo ts.
        andamento = conn.execute(
            "SELECT substr(ts,1,7) AS mese, event, COUNT(*) AS quante "
            "FROM node_stats GROUP BY mese, event ORDER BY mese DESC LIMIT 36").fetchall()
        ricerche_frequenti = conn.execute(
            "SELECT testo, numero, volte, risultati FROM ricerche "
            "ORDER BY volte DESC LIMIT 10").fetchall()
        ricerche_vuote = conn.execute(
            "SELECT testo, numero, volte FROM ricerche "
            "WHERE risultati=0 ORDER BY volte DESC LIMIT 10").fetchall()
        totale_ricerche = conn.execute("SELECT COUNT(*) c FROM ricerche").fetchone()["c"]
        totale_vuote = conn.execute(
            "SELECT COUNT(*) c FROM ricerche WHERE risultati=0").fetchone()["c"]
        totale_preferiti = conn.execute("SELECT COUNT(*) c FROM preferiti").fetchone()["c"]
    return templates.TemplateResponse(request, "admin/statistiche.html", {
        "user": user,
        "top_aperture": [dict(r) for r in top_aperture],
        "top_download": [dict(r) for r in top_download],
        "top_zip": [dict(r) for r in top_zip],
        "andamento": [dict(r) for r in andamento],
        "ricerche_frequenti": [dict(r) for r in ricerche_frequenti],
        "ricerche_vuote": [dict(r) for r in ricerche_vuote],
        "totale_ricerche": totale_ricerche,
        "totale_vuote": totale_vuote,
        "totale_preferiti": totale_preferiti,
    })
