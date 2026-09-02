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
