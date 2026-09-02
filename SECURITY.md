# Security Policy

Photocarcifo è un progetto in produzione, con dati reali di clienti. Prendo sul serio qualunque segnalazione di sicurezza.

## Segnalare una vulnerabilità

**Non aprire una issue pubblica** per vulnerabilità che potrebbero essere sfruttate prima di una correzione.

Segnala privatamente tramite [GitHub Security Advisories](../../security/advisories/new) di questo repository, oppure via email all'indirizzo indicato nel profilo GitHub dell'autore.

Includi, se possibile:

- una descrizione del problema e del suo impatto potenziale;
- passi per riprodurlo;
- versione/commit interessato.

Rispondo di norma entro qualche giorno. Se il problema è confermato, lavorerò a una correzione prima di qualunque divulgazione pubblica; il credito per la segnalazione responsabile è sempre benvenuto e verrà riconosciuto, se lo desideri.

## Cosa è coperto

Questo repository contiene il codice sorgente dell'applicazione. Non contiene, e non deve mai contenere, credenziali, chiavi, dati di clienti o informazioni sull'infrastruttura di produzione: se ne trovi, trattalo comunque come una segnalazione di sicurezza a sé, con priorità alta.

## Scope

Vulnerabilità applicative nel codice di questo repository (autenticazione, autorizzazione, gestione sessioni, upload, injection, XSS, CSRF, ecc.) sono nello scope. Problemi relativi a infrastruttura, hosting o servizi di terze parti non documentati in questo repository non sono nello scope di questa policy.
