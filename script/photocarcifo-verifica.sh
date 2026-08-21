#!/bin/bash
# Verifica rapida dello stato del sito. Usata dopo un riavvio.
R="--resolve photocarcifo.ch:443:127.0.0.1 -k"
echo "=== in piedi da: $(uptime -p) ==="
echo "=== servizi ==="
for s in photocarcifo nginx fail2ban photocarcifo-sentinella.timer \
         photocarcifo-scan.timer photocarcifo-numeri.timer \
         photocarcifo-pregen.timer photocarcifo-notte.timer \
         photocarcifo-covers.timer photocarcifo-rapporto.timer; do
    printf "  %-34s %s\n" "$s" "$(systemctl is-active "$s" 2>/dev/null)"
done
echo "=== archivio fotografie collegato ==="
mountpoint -q /mnt/magazzino && echo "  si" || echo "  NO"
echo "=== pagine ==="
fail=0
for L in it en fr de es; do
  for u in "/" "/n/bmx" "/search?q=110" "/recensioni" "/privacy"; do
    c=$(curl -s -b "pc_lang=$L" $R -o /dev/null -w "%{http_code}" "https://photocarcifo.ch$u")
    [ "$c" = 200 ] || { echo "  KO $L $u -> $c"; fail=1; }
  done
done
[ $fail = 0 ] && echo "  25 su 25 a posto"
echo "=== immagini e reindirizzamenti ==="
for u in /thumb/43293 /social/37493 /admin/login /sitemap.xml; do
    printf "  %-18s %s\n" "$u" "$(curl -s $R -o /dev/null -w '%{http_code}' "https://photocarcifo.ch$u")"
done
printf "  %-18s %s\n" "vecchia galleria" "$(curl -s -o /dev/null -w '%{http_code}' 'https://photocarcifo.ch/index.php?/category/BMX')"
echo "=== errori applicativi dall'avvio ==="
journalctl -u photocarcifo -b --no-pager 2>/dev/null | grep -ciE traceback
