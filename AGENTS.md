# MoarCoal

Personal finance app (taxes/ELSTER, receipts, real estate). Scaffold spec is done; the Durchstich (#27), Abschnitt 2 (#46), the content map (#61, incl. Abschnitt 3 / Anlage N) the UI/tidy-up map (#129) and the architecture map (#215) are built. New content gets its own Wayfinder map. Docs and app text in German; code and identifiers in English.

## Where things are

- `CONTEXT.md`: glossary. Use its terms in code and docs; add each new term there as soon as it's settled.
- `PRINCIPLES.md`: architecture principles. Every change keeps them; read them before you build, and ask instead of breaking one.
- `docs/adr/`: architecture decisions. Read the ones that touch your area before you change anything.
- `docs/grundgeruest.md`: architecture spec of the scaffold (Datenebene, Module, contract, storage), merged from the map. Start here before building.
- [Wayfinder-Karte: Architektur vertiefen #215](https://github.com/oiff2/MoarCoal/issues/215) (closed): deep modules for year membership of documents (`belongs_to_year`), Eingang classification (`Incoming`), field kind and field row of an Anlage (`FieldMeaning`, `anlage_view`) and the lines of the Lohnsteuerbescheinigung (`CERTIFICATE_LINES`). Its Decisions list is the index to why `documents.py`, `incoming.py`, the field/page code in `modules/tax_year/` and `work/wage_tax/values.py` are shaped this way. Its code-review leftovers (#222–#230) are triaged.
- [Wayfinder-Karte: Oberfläche bauen und Module aufräumen #129](https://github.com/oiff2/MoarCoal/issues/129): UI frame (header, sidebar, light/dark, status language), module cut (a module is what a user switches off as a whole; one page per module, Steuerjahr mirrors Mein ELSTER), write-path rules in `apply`, duplicate logic removed. Its Decisions list is the index to why the code is shaped this way.
- [Wayfinder-Karte: Inhalte nach dem Durchstich #61](https://github.com/oiff2/MoarCoal/issues/61) (closed): global UI prototype, Belege page, Aussteller, Steuerjahr Anlage N with Abschnitt 3. Abschnitt 2 ([#46](https://github.com/oiff2/MoarCoal/issues/46)) and the Durchstich ([#27](https://github.com/oiff2/MoarCoal/issues/27)) are done.
- [Wayfinder-Karte: Grundgerüst MoarCoal](https://github.com/oiff2/MoarCoal/issues/1) (closed): decisions behind the spec, one sub-issue per design question.
- `src/moarcoal/`: layers by path. `web/` is the binding (app factory, security, pages of the data-layer Bausteine, `links.py` for every address); FastAPI is imported only there, in `modules/` and in `registration.py` (the test core enforces it). `modules/` holds the modules with their own pages: `work/` (sub-parts `workplace/`, `wage_tax/`, `trips/`) and `tax_year/`. `storage/` and `values/` plus the flat files (`documents.py`, `incoming.py`, `block_findings.py`, …) are the data layer; `__main__.py` and `instance.py` the start. Templates and static files sit in `templates/` and `static/`. Spec §4 lists what each module contains.
- `erkenntnisse.md`: lessons from the predecessor project Kohlebau. Use it for orientation; it is not a spec.

## Privacy

Use made-up example values in everything that reaches git or GitHub (commits, issues, comments). Real personal data (amounts, addresses, names, tax IDs, account numbers) stays out.

`tools/privacy_guard.py` enforces this: git hooks in `.githooks/` (enable once per clone with `git config core.hooksPath .githooks`) and a Claude Code hook on `gh` commands. It checks IBANs, Steuer-IDs, Steuernummern, e-mails and a local denylist at `~/.config/moarcoal/sperrliste.txt` (never in the repo). Deliberately made-up values that trip it go in `tools/erlaubte_beispielwerte.txt`.

## Agent skills

- **Issues**: GitHub Issues (oiff2/MoarCoal) via `gh`. See `docs/agents/issue-tracker.md`.
- **Triage labels**: see `docs/agents/triage-labels.md`.
- **Domain docs**: single context. See `docs/agents/domain.md`.

## Glossar

- Jeder Fachbegriff steht in `CONTEXT.md`, bevor er in Code oder Oberfläche verwendet wird. Neue Begriffe nur, wo es kein Wort aus ELSTER, Steuerrecht oder Alltag gibt.
- Begriffe mit eigenem Typ im Code tragen `(Code: \`Name\`)` im Eintrag; das ist die einzige Zuordnung Deutsch ↔ Englisch.
- In MoarCoal geprägte Begriffe tragen den Tag `_(geprägt)_` hinter dem Namen. Obergrenze 30; darüber warnt der Testkern und empfiehlt den Skill `glossar-review`.
- Oberflächentexte stehen direkt in den Jinja-Vorlagen (nur Deutsch, keine Übersetzungsschicht).
- Tests im schnellen Testkern prüfen: _Avoid_-Wörter in Vorlagen (mit kleiner Ausnahmeliste, z. B. Schweregrade), jeder `Code:`-Name existiert im Code, kein Typ trägt einen gemiedenen englischen Namen.
