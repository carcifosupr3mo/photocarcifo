#!/usr/bin/env bash
# Prepara la chiavetta di emergenza chiedendo le credenziali.
# I dati inseriti finiscono in chiaro nel file HTML: la cartella e'
# leggibile solo da root ed e' esclusa dai salvataggi automatici.
set -uo pipefail

DEST="/opt/photocarcifo/EMERGENZA-NATH"
umask 077
mkdir -p "$DEST"
chmod 700 "$DEST"

echo "═══════════════════════════════════════════════"
echo "  Chiavetta di emergenza"
echo "═══════════════════════════════════════════════"
echo ""
echo "Ti chiedo i dati uno alla volta."
echo "Premi Invio per saltare quelli che non vuoi mettere."
echo ""

chiedi(){ read -rp "  $1: " R; echo "${R:-—}"; }
chiedi_nascosto(){ read -rsp "  $1: " R; echo "" >&2; echo "${R:-—}"; }

echo "── Accesso al sito ──"
SITO_UTENTE=$(chiedi "utente del pannello")
SITO_PW=$(chiedi_nascosto "password del pannello")
APP_2FA=$(chiedi "nome dell'app del codice a 6 cifre (es. Google Authenticator)")
echo ""

echo "── Server Proxmox ──"
PVE_PW=$(chiedi_nascosto "password di root")
echo ""

echo "── Archivio Synology ──"
NAS_UTENTE=$(chiedi "utente")
NAS_PW=$(chiedi_nascosto "password")
echo ""

echo "── Account Google del sito ──"
GOOGLE_MAIL=$(chiedi "indirizzo")
GOOGLE_PW=$(chiedi_nascosto "password")
echo ""

echo "── Dominio photocarcifo.ch ──"
REG_NOME=$(chiedi "dove è registrato (es. Infomaniak, Hostpoint)")
REG_UTENTE=$(chiedi "utente")
REG_PW=$(chiedi_nascosto "password")
echo ""

echo "── Persona da contattare per aiuto tecnico ──"
AIUTO_NOME=$(chiedi "nome")
AIUTO_TEL=$(chiedi "telefono")
echo ""

# protezione minima contro caratteri che romperebbero l'HTML
pulisci(){ printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }

cat > "$DEST/APRI-QUESTO.html" << HTMLEOF
<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Photocarcifo — cosa fare</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;line-height:1.6;
  color:#0a0c14;background:#f4f6fa;padding:1.2rem;max-width:40rem;margin:0 auto}
h1{font-size:1.6rem;margin-bottom:.3rem}
.sub{color:#5b6070;margin-bottom:1.8rem;font-size:.95rem}
h2{font-size:1.1rem;margin:2rem 0 .8rem;color:#2b4bff}
.box{background:#fff;border:1px solid #e2e5ec;border-radius:12px;
  padding:1.1rem;margin-bottom:1rem}
.cred{background:#fffbe6;border:1px solid #f0dfa0}
.cred p{margin-bottom:.7rem;font-size:.95rem;word-break:break-word}
.cred b{display:block;font-size:.72rem;text-transform:uppercase;
  letter-spacing:.06em;color:#8a7a30;margin-bottom:.1rem}
.cred code{font-family:ui-monospace,monospace;font-size:1rem;
  background:#fff;padding:.15rem .4rem;border-radius:4px;
  border:1px solid #e8dfc0;user-select:all}
ol{padding-left:1.3rem} li{margin-bottom:.7rem}
a.btn{display:block;background:#2b4bff;color:#fff;text-align:center;
  padding:.9rem;border-radius:999px;text-decoration:none;font-weight:600;
  margin:1rem 0}
.calma{background:#e8f5ee;border-color:#a8d5bd}
.attenzione{background:#fdeaed;border-color:#f0b6c0}
small{color:#5b6070;font-size:.85rem}
</style>
</head>
<body>

<h1>Photocarcifo</h1>
<p class="sub">Cosa fare se devi occupartene tu.</p>

<div class="box calma">
<h2 style="margin-top:0">Prima di tutto: niente panico</h2>
<p>Il sito funziona da solo. Ogni notte si aggiorna, si salva e, se
qualcosa va storto, si ripara da sé. Le fotografie sono al sicuro in due
posti diversi e <b>non si perdono</b> qualunque cosa succeda al sito.</p>
<p style="margin-top:.6rem">Puoi anche non fare nulla per mesi: resterà
online.</p>
</div>

<h2>Entrare nel sito</h2>
<a class="btn" href="https://photocarcifo.ch/admin">Apri il pannello</a>
<div class="box cred">
<p><b>utente</b><code>$(pulisci "$SITO_UTENTE")</code></p>
<p><b>password</b><code>$(pulisci "$SITO_PW")</code></p>
<p><b>codice a 6 cifre</b>si trova nell'app $(pulisci "$APP_2FA")<br>
<small>sul telefono di Nathan. Se non è raggiungibile, vedi in fondo.</small></p>
</div>

<h2>Cosa puoi fare</h2>
<div class="box">
<ol>
<li><b>Caricare foto</b> — voce «Carica foto»</li>
<li><b>Mandare le foto a un cliente</b> — «Album», tre puntini
sull'album, «Condivisione», «Copia link»</li>
<li><b>Vedere cosa ha scelto un cliente</b> — voce «Preferite»</li>
<li><b>Calendario raduni</b> — voce «Raduni»</li>
</ol>
</div>

<h2>Se il sito non si apre</h2>
<div class="box">
<ol>
<li>Collegati alla rete di casa</li>
<li>Apri <b>192.168.1.200</b> nel browser</li>
<li>Entra con utente <b>root</b> e password
<code>$(pulisci "$PVE_PW")</code></li>
<li>A sinistra cerca <b>206</b> e toccalo</li>
<li>In alto premi <b>Riavvia</b></li>
<li>Aspetta due minuti e riprova</li>
</ol>
<p><small>Nove volte su dieci basta questo.</small></p>
</div>

<h2>Archivio delle fotografie</h2>
<div class="box cred">
<p><b>indirizzo</b><code>192.168.1.11</code></p>
<p><b>utente</b><code>$(pulisci "$NAS_UTENTE")</code></p>
<p><b>password</b><code>$(pulisci "$NAS_PW")</code></p>
</div>

<h2>Account Google del sito</h2>
<div class="box cred">
<p><b>indirizzo</b><code>$(pulisci "$GOOGLE_MAIL")</code></p>
<p><b>password</b><code>$(pulisci "$GOOGLE_PW")</code></p>
<p><small>Serve per i rapporti settimanali e per Search Console.</small></p>
</div>

<h2>Dominio photocarcifo.ch</h2>
<div class="box cred">
<p><b>registrato presso</b>$(pulisci "$REG_NOME")</p>
<p><b>utente</b><code>$(pulisci "$REG_UTENTE")</code></p>
<p><b>password</b><code>$(pulisci "$REG_PW")</code></p>
<p><small>Va rinnovato ogni anno, altrimenti l'indirizzo si perde.</small></p>
</div>

<h2>Se serve aiuto tecnico</h2>
<div class="box">
<p><b>$(pulisci "$AIUTO_NOME")</b><br>$(pulisci "$AIUTO_TEL")</p>
<p style="margin-top:.7rem">Il progetto è documentato: dagli gli altri
file di questa chiavetta, ci troverà tutto.</p>
</div>

<h2>Se il codice a 6 cifre non è disponibile</h2>
<div class="box attenzione">
<p>Si può togliere, ma serve qualcuno che sappia usare un server.
Consegnagli questa istruzione:</p>
<p style="font-family:ui-monospace,monospace;font-size:.85rem;background:#fff;
padding:.7rem;border-radius:6px;margin-top:.6rem">
entrare nel container 206 e lanciare<br><br>
<b>photocarcifo-recupero.sh</b></p>
</div>

<h2>Le fotografie</h2>
<div class="box calma">
<p>Sono la cosa insostituibile, e stanno in due posti:</p>
<ol>
<li>l'archivio di casa (il Synology)</li>
<li>un disco esterno collegato a esso</li>
</ol>
<p style="margin-top:.6rem">Il sito è solo la vetrina: anche se sparisse,
le fotografie restano. <b>Non cancellare mai nulla dall'archivio.</b></p>
</div>

<p style="text-align:center;color:#5b6070;font-size:.85rem;margin:2rem 0 1rem">
Aggiornato il $(date '+%d/%m/%Y')
</p>

</body>
</html>
HTMLEOF

chmod 600 "$DEST/APRI-QUESTO.html"

cp /opt/photocarcifo/MAPPA/MAPPA.txt "$DEST/" 2>/dev/null
cp /opt/photocarcifo/MAPPA/Photocarcifo-Mappa.pdf "$DEST/" 2>/dev/null

cat > "$DEST/LEGGIMI.txt" << 'EOF'
CHIAVETTA DI EMERGENZA — PHOTOCARCIFO

Tocca il file  APRI-QUESTO.html
Si apre nel browser del telefono e spiega tutto,
comprese le password.

Gli altri file servono a un tecnico, se dovesse servire.
EOF
chmod 600 "$DEST"/*

unset SITO_PW PVE_PW NAS_PW GOOGLE_PW REG_PW

echo "═══════════════════════════════════════════════"
echo "  Fatto"
echo "═══════════════════════════════════════════════"
echo ""
echo "Cartella: $DEST"
ls -1 "$DEST" | sed 's/^/  /'
echo ""
echo "Ora copia questi file sulla chiavetta, poi valuta di"
echo "cancellare la cartella dal server:"
echo "  rm -rf '$DEST'"
echo ""
echo "Contiene password in chiaro: e' esclusa dai salvataggi"
echo "automatici e leggibile solo da root."
