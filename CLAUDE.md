## graphify

This project has a graphify knowledge graph at .graphify/.

Rules:
- For codebase or architecture questions, when `.graphify/graph.json` exists, first run `graphify query "<question>"` (or `graphify path "<A>" "<B>"` / `graphify explain "<concept>"`); these return a scoped subgraph, usually much smaller than `GRAPH_REPORT.md` or raw grep output
- If .graphify/wiki/index.md exists, navigate it instead of reading raw files
- If .graphify/graph.json is missing but graphify-out/graph.json exists, run `graphify migrate-state --dry-run` first; if tracked legacy artifacts are reported, ask before using the recommended `git mv -f graphify-out .graphify` and commit message
- If .graphify/needs_update exists or .graphify/branch.json has stale=true, warn before relying on semantic results and run /graphify . --update when appropriate
- Before proposing or committing .graphify artifacts, run `graphify portable-check .graphify`; commit-safe graph artifacts must use repo-relative paths, and never commit .graphify/branch.json, .graphify/worktree.json, .graphify/needs_update, or .graphify/cache/. If a repo already tracks any of them, first add them to .gitignore, then propose `git rm --cached .graphify/branch.json .graphify/worktree.json .graphify/needs_update` and `git rm -r --cached .graphify/cache`; never mutate git state without asking
- Before deep graph traversal, prefer `graphify summary --graph .graphify/graph.json` for compact first-hop orientation
- For review impact on changed files, use `graphify review-delta --graph .graphify/graph.json` instead of generic traversal
- Read `.graphify/GRAPH_REPORT.md` only for broad architecture review or when `query` / `path` / `explain` do not surface enough context
- After modifying code files in this session, run `npx graphify hook-rebuild` to keep the graph current

## Gerarchia delle fonti per richieste su questo progetto

1. Istruzione dell'utente corrente
2. `PROJECT_KNOWLEDGE.md` (architettura, config, infra, decisioni, stato, bug noti — §41 spiega l'integrazione con Graphify)
3. Graphify (`explain`/`path`/`summary`) per localizzare file/funzioni/dipendenze coinvolte
4. Risultati già nel contesto della sessione corrente
5. Ricerca mirata (grep/glob ristretto ai file indicati da Graphify)
6. Lettura diretta di file — solo le sezioni identificate come rilevanti, mai scansione integrale "per sicurezza"

Non rileggere file già letti in sessione. Non caricare l'intero PROJECT_KNOWLEDGE.md se basta una sezione.

## Agenti — usa solo quelli pertinenti, mai tutti di default

- Modifica normale: web-developer → code-reviewer (+ tester se logica non banale)
- Bug: debugger → web-developer → code-reviewer → tester
- Tocca auth/permessi/upload/password/token/endpoint sensibili: security-reviewer obbligatorio, in parallelo a code-reviewer
- Query lente/scanner/OCR/immagini/carichi: performance-reviewer
- Template/CSS/responsive/UX: ui-ux-reviewer
- Modifica banale/documentale: nessun agente aggiuntivo
- Reviewer paralleli operano sul diff/file coinvolti, non sull'intero repo

## Token & Context Efficiency Policy

Regole vincolanti per ridurre cache read/token/contesto ripetuto tra sessioni. Non ripetere queste regole nei prompt: bastano istruzioni brevi ("implementa X seguendo CLAUDE.md e PROJECT_KNOWLEDGE.md").

- **Ponytail** (`/ponytail`, plugin lato client): durante sessioni lunghe, dopo ogni fase completata comprimi/scarta log, diff vecchi, output test già passati, output agenti già sintetizzati — mantieni sempre obiettivo, vincoli, file modificati, decisioni, problemi aperti, test falliti, TODO correnti. Se il plugin non è disponibile in un dato contesto di esecuzione (es. subagent isolato), dichiaralo invece di fingere di averlo usato.
- **Output terminale compatto**: `pytest -q` non `-vv`; `git diff --stat` o `git diff -- <file>` non il diff intero del repo; `journalctl -n 100` non completo; `git status --short` quando basta. Filtra prima di stampare, non dopo.
- **Test mirati prima della suite completa**: modifica → test specifici sul file toccato → review → fix → suite completa solo a fine task, non dopo ogni riga.
- **Non rileggere/riverificare cose già accertate in sessione**: stesso file, stessa query Graphify, stesso agente sulla stessa domanda — riusa il risultato già ottenuto. Ri-verifica solo se il codice relativo è cambiato nel frattempo.
- **Sessioni più corte**: una macro-feature completata, testata, committata (e pushata quando pertinente) è un confine naturale — preferire una sessione nuova a continuare ad accumulare contesto indefinitamente. Lasciare nel commit/PROJECT_KNOWLEDGE.md quanto serve alla sessione successiva per ripartire senza dover rileggere tutto.
- **Sub-agent**: contesto minimo — solo task, requisiti pertinenti, diff, file realmente coinvolti, errori/test rilevanti. Mai l'intera conversazione, l'intero PROJECT_KNOWLEDGE.md, o l'intero repo.
- **Cache read**: non va "azzerata" — leggere dalla cache è più economico che rigenerare input. L'obiettivo è ridurre dimensione-del-contesto × numero-di-chiamate: prima di ogni tool/agent importante, chiedersi se si sta passando più contesto di quanto serva.

### Standard Task Workflow

1. leggi solo il contesto necessario (sezioni PROJECT_KNOWLEDGE.md pertinenti, non il file intero)
2. Graphify per restringere il perimetro (2-5 file, non scansione integrale)
3. apri solo i file minimi indicati
4. implementazione
5. test mirati
6. agenti solo quelli pertinenti (vedi sezione sopra)
7. Ponytail per comprimere contesto non più necessario
8. suite completa finale
9. commit
10. push (solo sul remote concordato, mai a caso)
11. nuova sessione se la macro-feature è conclusa
