# MoarCoal

Personal finance app (taxes/ELSTER, receipts, real estate). Scaffold spec is done; the Durchstich (#27), Abschnitt 2 (#46) and Abschnitt 3 (from #61) are built and merged. Current work: build the UI and tidy the modules on a Wayfinder map (#129). Docs and app text in German; code and identifiers in English.

## Where things are

- `CONTEXT.md`: glossary. Use its terms in code and docs; add each new term there as soon as it's settled.
- `PRINCIPLES.md`: architecture principles. Every change keeps them; read them before you build, and ask instead of breaking one.
- `docs/adr/`: architecture decisions. Read the ones that touch your area before you change anything.
- `docs/grundgeruest.md`: architecture spec of the scaffold (Datenebene, Module, contract, storage), merged from the map. Start here before building.
- [Wayfinder-Karte: Oberfläche bauen und Module aufräumen #129](https://github.com/oiff2/MoarCoal/issues/129): the current work. Builds the UI decided in prototype #62 (header, draggable sidebar, light/dark, shared status language), takes stock of the code, decides which parts are modules and what each holds, then restructures and removes duplicate logic. No new content. Read its Notes first: building is part of this map, no duplicate functionality, keep the glossary and code small, reuse existing building blocks.
- [Wayfinder-Karte: Inhalte nach dem Durchstich #61](https://github.com/oiff2/MoarCoal/issues/61) (closed): global UI layout (#62), Belege page (#63), Aussteller (#67), Steuerjahr Anlage N with Abschnitt 3 (#64). Abschnitt 2 ([#46](https://github.com/oiff2/MoarCoal/issues/46)) and the Durchstich ([#27](https://github.com/oiff2/MoarCoal/issues/27)) are done.
- [Wayfinder-Karte: Grundgerüst MoarCoal](https://github.com/oiff2/MoarCoal/issues/1) (closed): decisions behind the spec, one sub-issue per design question.
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
