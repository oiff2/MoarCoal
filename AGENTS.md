# MoarCoal

Personal finance app (taxes/ELSTER, receipts, real estate). Scaffold spec is done; the Durchstich (#27) is built, Abschnitt 2 (#46) is in progress. Docs and app text in German; code and identifiers in English.

## Where things are

- `CONTEXT.md`: glossary. Use its terms in code and docs; add each new term there as soon as it's settled.
- `docs/adr/`: architecture decisions. Read the ones that touch your area before you change anything.
- `docs/grundgeruest.md`: architecture spec of the scaffold (Datenebene, Module, contract, storage), merged from the map. Start here before building.
- [Abschnitt 2 #46](https://github.com/oiff2/MoarCoal/issues/46): the current work, second build stage per `docs/grundgeruest.md` (section „Bauabschnitte“), one sub-issue per slice. Build only what it needs. The first stage was the [Durchstich #27](https://github.com/oiff2/MoarCoal/issues/27).
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
