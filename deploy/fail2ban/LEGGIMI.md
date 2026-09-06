# fail2ban — copia versionata della configurazione in uso

Questi file **non sono quelli attivi**: quelli vivono in `/etc/fail2ban/`,
fuori dal repository, come tutta la configurazione di sistema. Qui ce n'e'
una copia perche' dal 06/09/2026 fail2ban non fa piu' soltanto "chiudi la
porta a questo indirizzo", e il disegno di come il sito blocca chi blocca
merita di stare scritto insieme al codice invece che solo dentro un
container che si puo' perdere.

Cosa c'e' dentro, in breve:

- `jail.d/photocarcifo.local` — le jail del sito. Quelle **web**
  (`photocarcifo-login`, `nginx-limit-req`, `nginx-botsearch`,
  `photocarcifo-manuale`) usano l'azione `photocarcifo-nginx`: niente
  regola nel firewall, l'indirizzo finisce in un elenco che nginx legge e
  chi e' bloccato vede la pagina `/bloccato` invece di un errore di rete.
  Quelle **non web** restano com'erano: `sshd` non ha una pagina da
  mostrare, e a `photocarcifo-scansioni` (tentativi di eseguire codice sul
  server) e' meglio non rispondere affatto che spiegare qualcosa.
- `action.d/photocarcifo-nginx.conf` — l'azione che chiama
  `script/photocarcifo-bloccati-nginx.py` (quello si' versionato).
- `filter.d/photocarcifo-manuale.conf` — il filtro della jail dei ban dati
  a mano dal bot Telegram (`/banip`): non puo' avere corrispondenza per
  costruzione, perche' quella jail deve riempirsi solo a comando.

Non ci sono segreti: nessun indirizzo di casa, nessun token, nessuna
chiave. Le reti in `ignoreip` sono gli intervalli privati standard.

Per rimettere tutto in piedi su una macchina nuova: copiare questi file
nei rispettivi `/etc/fail2ban/…`, creare `/var/log/photocarcifo-manuale.log`
(vuoto, serve solo perche' la jail manuale abbia un log da guardare),
collegare `script/photocarcifo-bloccati-nginx.py` in `/usr/local/bin/`, poi
`fail2ban-client -t` e `systemctl restart fail2ban`. Il runbook completo
sta nella copia sul NAS (`deploy/photocarcifo-export-config.sh`).
