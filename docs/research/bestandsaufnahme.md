# Bestandsaufnahme: Aufteilung, Modulgrenzen und doppelte Logik

Teil von [#133](https://github.com/oiff2/MoarCoal/issues/133) (Karte #129), Grundlage für den Zuschnitt der Module (#134) und die Aufräum-Slices. Stand: Commit `0202d70` auf `main`. Es wurde kein Code geändert. Jeder Punkt nennt Datei und Zeile (Pfade relativ zu `src/moarcoal/`). Verhaltensunterschiede bei Beinahe-Dubletten sind mit `uv run python` geprüft (Abschnitt 3.6). Begriffe: Glossar (`CONTEXT.md`), dazu das Vokabular aus `codebase-design` (Modul im Sinne von „Schnittstelle plus Implementierung“, Tiefe, Naht). Ein **Modul** mit großem M ist hier immer ein MoarCoal-Modul mit Modulanmeldung; wo der allgemeine Sinn gemeint ist, steht „Baustein“ oder „Datei“.

Umfang heute: 11 005 Zeilen Python. Davon liegen 4 034 flach in `src/moarcoal/`, 1 619 in `storage/`, 1 396 in `values/`, 2 175 in `modules/work/` und 1 772 in `modules/tax_year/`.

## Kurzfassung

- **Module kennen sich nicht (Prinzip 2): eingehalten.** Weder `modules/work` noch `modules/tax_year` importiert aus dem anderen. Das Steuerjahr kennt die Werte von Arbeit nur über die Schlüssel als Text (`modules/tax_year/anlage_n.py:33-45`).
- **Die Datenebene ist auf drei Orte verteilt:** `storage/`, `values/` und rund zwölf flache Dateien. `values/engine.py:5-10` importiert fünf flache Dateien und `registration.py`, das wiederum FastAPI importiert (`registration.py:6`). Welche flache Datei zur Datenebene gehört und welche zur Anbindung, sieht man nur am Inhalt. Drei Dateien mischen beides: `incoming.py`, `issuer_field.py` und `document_list.py`.
- **Routen stehen in der Datenebene (Prinzip 1),** obwohl es `links.py` gibt: `values/engine.py:220`, `expected_documents.py:16`, `web.py:41`, `incoming.py:130-151`, `document_list.py:233`. Die Belege-Seite kennt außerdem Arten aus den Modulen (`document_list.py:35-41`).
- **Fünf Invarianten prüft nur die Seite vor `apply` (Prinzip 3).** Alle fünf lassen sich am Schreibweg vorbei schreiben (geprüft, siehe 3.6): dieselbe Datei zweimal als Dokument, ein Ordner zweimal ausgeblendet, ein Erwarteter Beleg ohne Dokumentart mit Bezugszeitraum, eine Eingabe „viele“ in einem Tage-Feld (danach bricht die Rechnung mit `ValueError` ab) und das Umbenennen des eigenen Ausstellers samt Abschalten von „Privatperson“ (dann fehlt der Name in der Sperrliste).
- **Eine Dublette mit echtem Fehlerrisiko:** `parse_cents` (`modules/work/pages.py:57`) liest „12.5“ als 125,00 € und „1e3“ als 1 000 €. `parse_german_number` (`values/model.py:63`) weist beides ab.
- **Arbeit besteht aus drei Teilen, die wenig miteinander zu tun haben:** Lohnsteuerbescheinigung (rund 250 Zeilen), Erste Tätigkeitsstätte und Arbeitsmittel (rund 450 Zeilen) sowie Dienstreisen mit Orten und Karte (rund 1 200 Zeilen). Das **Steuerjahr** dagegen hängt durchgehend an `FormField` und ist zusammenhängend. Nur seine Eingaben (Nr. 58/65) sind ein zweiter Mechanismus für Nutzereingaben neben dem in Arbeit.

---

## 1. Paket-Aufteilung

### 1.1 Jede flache Datei und ihre Schicht

Schichten: **D** = Datenebene (gespeicherte Daten und Bausteine für alle Module), **A** = Anbindung (Seiten, Routen, HTTP), **M** = gehört fachlich zu einem Modul, **W** = Werkzeug/Start (Prozess, CLI, Absicherung).

| Datei | Zeilen | Schicht | Inhalt | Richtiger Ort? |
|---|---|---|---|---|
| `__main__.py` | 151 | W | CLI `start/stop/restart`, uvicorn | ja |
| `instance.py` | 129 | W | eigene Instanz erkennen, Port freimachen; `choose_action` rein (`instance.py:47`) | ja, gehört zu `__main__` |
| `security.py` | 60 | A/W | Middleware Host/Origin/CSP (ADR 0007) | ja |
| `app.py` | 178 | A | App-Fabrik, Router-Liste (`app.py:93-102`) **und** die Befundliste als drei Routen in `create_app` (`app.py:104-176`) | Befundliste-Routen gehören in eine eigene Seiten-Datei wie alle anderen |
| `web.py` | 123 | A | Helfer der Seiten (`render`, `store_of`, `module_state`), dazu `year_of` (`web.py:26`), `format_eur` (`web.py:21`) und `entry_url` mit fester Route (`web.py:41`) | `year_of` ist Fachlogik (Jahresbereich), `entry_url` gehört zu `links.py` |
| `links.py` | 10 | A | Adressen der Bausteine: nur Dokument und Aussteller | ja, aber unvollständig (siehe 3.2) |
| `previews.py` | 56 | A | Medientyp, CSP, `file_response` mit `HTTPException` (`previews.py:43-56`) | ja (Anbindung der Belege) |
| `site_pages.py` | 248 | A | Belege-Seite, Reiter Ablage, Weiterleitungen `/eingang…` | ja |
| `document_list.py` | 238 | A **+ D** | Reiter Dokumente (A); `document_state` (`:54`), `filter_documents` (`:70`) und `read_document_choice` (`:153`) sind reine Fachlogik | mischt beides |
| `document_pages.py` | 142 | A | Routen `/dokumente/{id}/…` | ja |
| `expected_documents_pages.py` | 199 | A | Reiter Erwartet | ja |
| `issuer_pages.py` | 260 | A | Seite Aussteller; `_references` (`:45`) und `_build` (`:66`) sind Fachlogik | überwiegend ja |
| `issuer_field.py` | 152 | D **+ A** | `search_issuers` (`:48`), `last_issuer` (`:76`), `resolve_issuer` (`:92`) sind rein; dazu die Route `/aussteller-suche` (`:124`) | mischt beides |
| `person_pages.py` | 73 | A | Startseite und `/person` | ja |
| `documents.py` | 253 | D | `DocumentKind` (`:44`), `take_in` (`:145`), `change_document` (`:211`), `duplicate_findings` (`:121`) | ja; das Wort „documents“ steht zugleich für `storage/documents.py` |
| `incoming.py` | 295 | D **+ A** | Eingang und Ausblenden (`:27-95`, D); Seitenmodell der Ablage mit Routen in `Row.preview_url` (`:115-151`), Baum, `IntakeFilter` als URL-Parameter (`:97`), `SiteListing` (`:249`) | mischt beides |
| `prefill.py` | 62 | D (Belege) | Vorbelegen aus dem Namen, rein | ja |
| `proposals.py` | 265 | D | auslesen, bestätigen, Befunde zu Vorschlag und Abgebrochener Auslesung | ja |
| `extraction.py` | 271 | D | Aufrufbaustein für Claude (einziger `claude`-Aufruf) | ja |
| `extraction_template.py` | 170 | D | Auslese-Vorlage | ja |
| `expected_documents.py` | 102 | D | Erwarteter Beleg: Stand je Jahr, Befunde | ja, aber mit Route (`:16`) |
| `issuers.py` | 25 | D | ein Befund „Dokument ohne Aussteller“ | Name verwechselbar mit `storage/issuers.py`, passt fachlich in eine Aussteller-Datei |
| `personal_details.py` | 101 | D | Angaben zur Person, eigener Aussteller (ADR 0009), rein | ja |
| `dismissals.py` | 40 | D | Befund ausblenden und einblenden | ja |
| `registration.py` | 138 | D (Vertrag) | `ModuleRegistration`, `ModuleState` | ja; hängt über `APIRouter` an FastAPI (`:6`, `:41`) |
| `defaults.py` | 9 | D | `DEFAULT_YEAR`, `MIN_YEAR`/`MAX_YEAR` | ja |
| `elster_html.py` | 160 | M (beide) | HTML-Leser für Mein ELSTER, genutzt von `modules/work/reading.py:13` und `modules/tax_year/reading.py:17` | ein gemeinsamer Modulbaustein; ELSTER ist ein Fachbegriff des Steuerjahrs, also keine Datenebene im engen Sinn |
| `place_search.py` | 123 | M (Arbeit) | Nominatim-Adapter und Fake; nur von `modules/work/trip_pages.py:40` und `trip_view.py:28` genutzt, eingesetzt über `app.state` (`app.py:82`) | gehört fachlich zu Dienstreisen/Orte; flach liegt die Datei nur, weil `create_app` sie einsetzt |

Daraus folgt:

- **Die Datenebene ist dreigeteilt.** Eintragsarten und Schreibweg liegen in `storage/`, Rechnen und Befunde in `values/`, die Vorgänge der Bausteine (aufnehmen, auslesen, ausblenden, Aussteller wählen, Angaben zur Person) flach. `values/engine.py:5-10` holt die Befunde der Bausteine aus fünf flachen Dateien. Die Datenebene hängt damit an Dateien, die man von außen nicht von Seiten-Code unterscheiden kann.
- **Drei Dateien mischen Kern und Anbindung:** `incoming.py`, `issuer_field.py` und `document_list.py`. Ein Test, der Prinzip 1 per Import prüfen wollte (etwa „Datenebene importiert nichts aus `fastapi`“), scheitert heute an `issuer_field.py:14` und `registration.py:6`.
- **Vorgänge mit `Store`:** `take_in`, `change_document` (`documents.py:145`, `:211`), `read_out`, `confirm` (`proposals.py:65`, `:181`), `dismiss` (`dismissals.py:13`) und `hide_folder`/`hide_file`/`unhide` (`incoming.py:66-95`) rufen `store.apply` selbst. Prinzip 4 verlangt eigentlich „Stand rein, Änderungen raus, die Anbindung übergibt an `apply`“. `take_in` und `read_out` müssen Dateien lesen bzw. Claude aufrufen und können deshalb nicht rein sein. `dismiss`, `confirm` und die Ausblend-Funktionen könnten es (vergleiche `personal_details_changes`, `personal_details.py:65`, das rein ist).

### 1.2 Mögliche Gruppierungen

**Option A: Pakete nach Schicht.** `moarcoal/data/` (oder Einordnung in `storage/`/`values/`) für alle D-Dateien, `moarcoal/web/` für alle A-Dateien samt `app.py`, `security.py`, `links.py`, `previews.py`, `moarcoal/cli/` für `__main__` und `instance`. Die gemischten Dateien werden vorher geteilt (`incoming.py` → Eingang/Ausblenden und Seitenmodell der Ablage; `issuer_field.py` → Kern und Route; `document_list.py` → `document_state`/`filter_documents`/`read_document_choice` und Reiter).
- Vorteil: Prinzip 1 lässt sich mit einem Import-Test durchsetzen (D importiert nie aus `web/`), und die Schichtung ist am Pfad ablesbar.
- Nachteil: Ein Baustein wie „Aussteller“ verteilt sich auf drei Pakete (`storage/issuers.py`, `data/issuers…`, `web/issuer_pages.py`). Wer am Aussteller arbeitet, springt zwischen ihnen hin und her.

**Option B: Pakete je Baustein (vertikal).** `moarcoal/belege/` (documents, incoming, prefill, previews, site_pages, document_list, document_pages, expected_documents samt Seiten, proposals), `moarcoal/issuers/` (issuers, issuer_field, issuer_pages), `moarcoal/person/` (personal_details, person_pages). Jedes Paket enthält Kern und Seiten, die Eintragsarten bleiben in `storage/`.
- Vorteil: Was zusammen geändert wird, liegt zusammen. Die Seitenleiste nennt Belege und Aussteller ohnehin als eigene Einträge (grundgeruest §6, „Allgemein“).
- Nachteil: Die Pakete sehen aus wie Module, sind aber keine. Sie lassen sich nicht abschalten, und die Datenebene braucht sie (Sperrliste über den Aussteller, Verweise auf Dokumente). Die Grenze zu den Modulen verschwimmt, und Prinzip 1 („Datenebene importiert keinen Seiten-Code“) lässt sich nur noch innerhalb jedes Pakets prüfen.

**Option C: flach bleiben, nur reparieren.** Die drei gemischten Dateien teilen, Routen nach `links.py` holen, `issuers.py` in `issuer_findings.py` umbenennen (oder mit dem Kern aus `issuer_field.py` zusammenlegen), die Befundliste-Routen aus `app.py` in eine `findings_pages.py` verschieben.
- Vorteil: kleiner Aufwand, kein Umzug, kaum Konflikte mit laufender Arbeit.
- Nachteil: 25 flache Dateien bleiben, und die Schicht lässt sich weiter nur am Inhalt erkennen.

Bewertung: C lohnt sich in jedem Fall und ist die Voraussetzung für A und B. Ob danach A oder B folgt, hängt an der Frage aus 2.3 (sind Belege und Aussteller „Bausteine mit Seiten“ oder „Module ohne Abschalten“?). Diese Frage gehört zu #134.

---

## 2. Modulgrenzen

### 2.1 Arbeit (`modules/work/`, 2 175 Zeilen)

Nach Zusammenhang gruppiert:

| Teil | Dateien und Zeilen | Hängt an |
|---|---|---|
| **Lohnsteuerbescheinigung** (rund 250 Zeilen) | `entries.py:75-91` (`WageTaxCertificate`), `reading.py` (101), `values.py:134-175` (vier Werte), Dokumentart in `__init__.py:25-33` | `elster_html.py`; sonst nichts in Arbeit. Liefert `work.tax_class`, `work.gross_wages`, `work.income_tax_withheld` und `work.soli_withheld` an das Steuerjahr (Anlage N Nr. 4-7) |
| **Erste Tätigkeitsstätte und Arbeitsmittel** (Nutzereingaben, rund 450 Zeilen) | `entries.py:31-72` (`UserInput`, `FirstWorkplace`, `WorkEquipment`), `values.py:56-131`, `values.py:249-268` (Befund `EQUIPMENT_GAP`), `pages.py` (351, allgemeines `EntryForm`-CRUD, `pages.py:124-137`) | nichts außerhalb |
| **Dienstreisen** (rund 800 Zeilen) | `entries.py:94-153` (`BusinessTrip`, `TripsConfirmation`, `check_confirmation`), `trips.py` (253, Tabelle → Änderungen, km-Satz `trips.py:38`), `trip_reading.py` (228, Reiseaufstellung und Übernahme), `trip_view.py` (135), `trip_pages.py:1-170`, `values.py:178-246`, `values.py:269-276` (Befund `TRIPS_TO_FILL`) | `proposals.proposals_of`, `extraction_template` |
| **Orte und Karte** (rund 400 Zeilen) | `places.py` (179), `germany_map.py` (38), `trip_pages.py:172-250`, Kartenteil von `trip_view.py:129-130`, dazu flach `place_search.py` (123) | nur Ortsnamen aus `BusinessTrip.places` |

Beobachtungen:

- Die **Lohnsteuerbescheinigung** ist in Arbeit ein Fremdkörper. Sie teilt mit den anderen Teilen nur `entries.yearly_path` (`entries.py:156-159`) und die Modulanmeldung. Fachlich ist sie Rohmaterial der Anlage N, genauso wie das Übertragungsprotokoll im Steuerjahr. Ihre Einlese-Regel ist fast eine Kopie der Protokoll-Regel (siehe 3.1, D5).
- **Dienstreisen mit Orten und Karte** machen mit rund 1 200 Zeilen mehr als die Hälfte von Arbeit aus. Sie haben eigene Seiten unter eigener Adresse (`trip_pages.py:45`, `/arbeit/dienstreisen`), eine eigene Bestätigung und eigene Befunde. Mit dem Rest von Arbeit verbindet sie nur die Übersicht `/arbeit`, die die Dienstreisen einbettet (`pages.py:20`, `pages.py:252`). Zum Steuerjahr laufen nur `work.trip_days`, `work.travel_fare` und `work.travel_total`.
- **Erste Tätigkeitsstätte und Arbeitsmittel** sind der Kern, den der Name „Arbeit“ verspricht. Hier steht das allgemeine CRUD für Nutzereingaben (`pages.py:124-351`). Die Dienstreisen nutzen es nicht, sie haben ihre eigene Tabelle.
- `pages.py:20` importiert `trip_view`, und `trip_view.py:27` importiert `values`. Die Übersicht hängt also am Dienstreise-Teil. Eine Abspaltung müsste hier eine Naht schaffen, etwa über den gemeinsamen Anzeigebaustein für fremde Werte.

Kandidaten (Optionen, die Entscheidung trifft #134):

1. **Dienstreisen (mit Orten) als eigenes Modul.** Das macht die Grenze sichtbar, die im Code schon besteht (eigene Adresse, eigene Werte, eigene Befunde). `/arbeit` zeigt Fahrtkosten dann nur noch über den Anzeigebaustein. Kosten: eine zweite Modulanmeldung, das Datenverzeichnis `users/<u>/work/places.json` (`places.py:63-64`) und die Jahresdateien müssten umziehen (Migration beim Start, ADR 0004), und der Schlüsselpräfix `work.` an drei Werten wechselt (bricht Schnappschüsse, deren `FrozenRef` den Schlüssel trägt).
2. **Lohnsteuerbescheinigung ins Steuerjahr.** Dann lägen beide eingelesenen ELSTER-Dokumente beisammen, und `elster_html.py` wäre ein Baustein nur noch eines Moduls. Kosten: Das Steuerjahr wird größer und rechnet dann eigene Werte statt fremde zu übernehmen (`anlage_n.py:399-405`). Gegen die Option spricht, dass die Bescheinigung auch für andere Verbraucher als die Anlage N Rohdaten liefert.
3. **Alles bleibt in Arbeit,** aber als Unterpakete `work/wage_tax/`, `work/trips/` und `work/workplace/`. Das bringt Lokalität ohne neue Modulanmeldung und ohne Migration. Es löst die Kopplung der Übersicht nicht, macht sie aber sichtbar.

### 2.2 Steuerjahr (`modules/tax_year/`, 1 772 Zeilen)

| Teil | Dateien und Zeilen |
|---|---|
| **Übertragungsprotokoll** (einlesen, ansehen, abgleichen) | `entries.py:20-53` (`ProtocolLine`, `ProtocolReading`), `reading.py` (96), `comparison.py:59-210` (Protokoll-Befunde, Gegenprobe der Struktur), `pages.py:50-63` |
| **Struktur und Felder der Anlage N je Jahr** | `structure.py` (131, Struktur aus `strukturen/`, Seiten), `fields.py` (231, `FormField`: runden, anzeigen, vergleichen), `anlage_n.py:82-288` (Feldkatalog 2025), `pages.py:66-122` |
| **Zuordnung der Werte** | `anlage_n.py:291-431` (übernimmt Arbeit-Werte, rundet) |
| **Eingaben Nr. 58/65** | `entries.py:55-78` (`FormInput`, `check_input`), `inputs.py` (36), `anlage_n.py:334-358`, `pages.py:125-166`, `fields.py:38-50` (`TypedInput`) |
| **Schnappschuss der Abgabe** | `comparison.py:213-262` (Abweichung zum Schnappschuss), `comparison.py:378-401` (`snapshot_on_filing`), Dokumentart in `__init__.py:27-37` |
| **Bescheid (EStB)** | `assessment.py` (113, Auslese-Vorlage), `comparison.py:265-359` (Bescheid-Abgleich) |

Beobachtungen:

- Alle sechs Teile hängen an `FormField` und `Forms` (`anlage_n.py:285-288`). Das Modul ist fachlich zusammenhängend: Es ist „die Anlage N eines Jahrs mit allem, womit man sie abgleicht“. Eine Abspaltung drängt sich nicht auf.
- Die **Eingaben Nr. 58/65** sind ein zweiter Mechanismus für Nutzereingaben. In Arbeit hat jede Eingabe eine eigene Eintragsart mit eigenem Formular (`FirstWorkplace.workdays_per_week`, `modules/work/entries.py:56`). Im Steuerjahr gibt es eine Eintragsart für alle Felder, verschlüsselt über die E-Kennung (`FormInput`, `modules/tax_year/entries.py:55-66`). Homeoffice-Tage (Nr. 58) sind fachlich so sehr „Arbeit“ wie die Urlaubstage (Nr. 28), stehen aber im Steuerjahr. Beide Wege sind vertretbar. Prinzip 7 verlangt aber, dass es einen Weg gibt, und das gehört zu #134.
- `comparison.py` (401 Zeilen) bündelt drei Abgleiche, die nur `latest_snapshot` und `_taken_order` teilen (siehe 4).
- `MODULE_KEY = "tax_year"` steht zweimal (`pages.py:23`, `comparison.py:45`). Die Adresse des Protokolls ebenfalls (`pages.py:172`, `comparison.py:79`).

### 2.3 Belege, Aussteller und Angaben zur Person: Bausteine oder modulartig?

Die Lage heute:
- Die Spezifikation führt sie als **Bausteine der Datenebene** (grundgeruest §2, ADR 0009 für Angaben zur Person, ADR 0003 für das Dokument). Ihre Eintragsarten registriert `open_store` fest (`storage/store.py:683-695`). Die Datenebene braucht sie: Verweise auf Dokumente (`storage/documents.py:90-97`), die Sperrliste über den Aussteller (`storage/issuers.py:84-92`), den Nutzer über die Angaben zur Person (`web.py:72-90`).
- In der **Form sind sie modulartig.** Jeder hat Seiten (Belege: `site_pages.py`, `document_list.py`, `document_pages.py`, `expected_documents_pages.py`, zusammen 827 Zeilen; Aussteller: `issuer_pages.py` und `issuer_field.py`, 412 Zeilen; Person: 73 Zeilen), eigene Befunde (`documents.py:121`, `issuers.py:10`, `expected_documents.py:72`, `proposals.py:133`, `:225`) und einen eigenen Eintrag in der Seitenleiste. Sie werden aber direkt in `app.py:95-102` und `values/engine.py:195-223` verdrahtet statt über eine Modulanmeldung.

Optionen:
1. **Bausteine mit Seiten (heute, nur geordnet).** Sie bleiben Datenebene und bekommen nach Option A oder B aus 1.2 ein Zuhause. Ihre Befunde sammelt die Datenebene weiter selbst, ihre Seiten liegen in der Anbindung. Das passt zu ADR 0009 („Profil als Modul verworfen“).
2. **Eine Anmeldung für Bausteine.** Eine schlanke Form von `ModuleRegistration` (Router, Befundquelle, Navigationseintrag, ohne Abschalten und ohne Werte) für Belege und Aussteller. `app.py` und `values/engine.py:195-223` werden dann zu Schleifen über diese Anmeldungen. Vorteil: Befunde und Router kommen auf einem Weg herein, und die Engine kennt `incoming`, `issuers` usw. nicht mehr namentlich. Nachteil: ein zweiter Anmeldetyp neben `ModuleRegistration`.
3. **Echte Module „Belege“ und „Aussteller“.** Das widerspricht Prinzip 1 und ADR 0009, denn die Datenebene bräuchte ein Modul. Nicht empfohlen.

---

## 3. Doppelte Logik und Prinzipienverstöße

### 3.1 Dubletten und Beinahe-Dubletten (Prinzip 7)

| Nr. | Was | Stellen | Unterschied |
|---|---|---|---|
| D1 | **Betrag aus deutschem Text** | `modules/work/pages.py:57-67` (`parse_cents`) und `values/model.py:63-71` (`parse_german_number`); dazu `modules/work/reading.py:37-42` (`_cents` auf Basis von `parse_german_number`) | **Verhalten weicht ab (geprüft):** `parse_cents` entfernt jeden Punkt, also wird „12.5“ zu 12 500 Cent (125 €), „1.2.3“ zu 12 300 und „1e3“ zu 100 000. `parse_german_number` gibt in allen drei Fällen `None`. Umgekehrt nimmt `parse_german_number` „5 €“ an, `parse_cents` nicht. Wer „12.5“ für 12,50 € tippt, speichert still 125 € |
| D2 | **Reisen und Bestätigung eines Jahrs** | `modules/work/values.py:178-184` (`_trips`, `_confirmation`) und `modules/work/trip_view.py:47-58` (`trips_of`, `confirmations_of`) mit `current_confirmation` in `trip_pages.py:115` | gleiche Logik: einmal auf `ModuleState`, einmal auf `Request` |
| D3 | **Neuester Vorschlag eines Dokuments** | `proposals.py:55-62` + `[-1]` an fünf Stellen: `proposals.py:236-239`, `document_list.py:61-63`, `:122/136`, `document_pages.py:133-139`, `modules/work/trip_view.py:83-84`, `trip_pages.py:124-126`; dazu eine eigene Fassung in `registration.py:102-109` (`max(created_at, id)`) | gleiche Reihenfolge, aber zwei Implementierungen. Arbeit liest Vorschläge am `ModuleState` vorbei über `store_of(request).state()` (`trip_view.py:83`, `trip_pages.py:124`) |
| D4 | **Auslese-Vorlage zur Dokumentart** (`kinds.get(kind or "")` → `.extraction_template`) | `proposals.py:77-78`, `document_pages.py:137-138`, `document_list.py:121/135`, `site_pages.py:164-165`, `registration.py:110-111` | gleich; fehlt als Funktion |
| D5 | **Kopf eines ELSTER-HTML prüfen** (Bezugszeitraum vorhanden, Belegart, Jahr passt) | `modules/work/reading.py:53-65` und `modules/tax_year/reading.py:72-82` | bis auf Texte gleich. `ParsedProtocol` (`modules/tax_year/reading.py:34-39`) wiederholt dabei die Felder von `ParsedHtml` |
| D6 | **Eingabe zu einem Feld finden** | `modules/tax_year/inputs.py:9-14` (`current_input`) und `modules/tax_year/anlage_n.py:338-345` | gleich, die Zeilen sind kopiert |
| D7 | **Reihenfolge nach `taken_in_at`** | `modules/tax_year/comparison.py:59-61` (`_taken_order`, ohne Zeitpunkt zuerst), `issuer_field.py:85-88` (`datetime.min`), `modules/work/trip_reading.py:228` (roh) | **Verhalten weicht ab (geprüft):** `statements` wirft `TypeError`, sobald ein Dokument ohne `taken_in_at` neben einem mit Zeitpunkt steht. Vorkommen kann das nur bei Dokumenten vor dem Feld `taken_in_at`; das Risiko ist gering, aber die Logik existiert dreimal |
| D8 | **Aussteller über Kennung holen** (Adresse bauen, `get`, `isinstance`, sonst 404) | `issuer_pages.py:87-95`, `:150-155`, `:185-191`, `issuer_field.py:71-73` (mit `isalnum` statt `ValueError`), ähnlich `expected_documents_pages.py:83-91`, `modules/tax_year/pages.py:52-59`, `modules/work/pages.py:155-159`, `proposals.py:263-265` | kleine Abweichungen im Umgang mit ungültigen Kennungen; fehlt als ein Helfer `entry_of(state, kind, id, owner)` |
| D9 | **Aussteller nach Text suchen** | `issuer_pages.py:61-63` (`_matches`) und `issuer_field.py:48-59` (`search_issuers`) | **Verhalten weicht ab (geprüft):** Leere Suche zeigt im Katalog alle, im Feld keinen (gewollt). Der Text „Musterfirma GmbH Niederlassung“ findet im Feld „Musterfirma GmbH“, im Katalog nicht, weil nur `search_issuers` auch prüft, ob der Name im Text steht. Ob der Katalog absichtlich strenger sucht, ist nicht dokumentiert |
| D10 | **Name und Aliasse als Liste** `(i.name, *i.aliases)` | `storage/issuers.py:64`, `:73`, `:104-105`, `issuer_field.py:44-45` (`_names`), `issuer_pages.py:63`, `:242`, `document_list.py:105`, `prefill.py:40` | gehört als Eigenschaft an `Issuer` |
| D11 | **„Eingang“ zweimal berechnet** | `incoming.py:32-44` (`incoming_files`) und `incoming.py:195-213` + `:262-264` (`site_rows`, `SiteListing.open_files`) | **gleiches Verhalten (geprüft,** 3 000 Zufallsfälle, 0 Abweichungen). Der Docstring sagt selbst „wie `incoming_files`“ (`:263`). Eine der beiden lässt sich auf die andere zurückführen |
| D12 | **Pfadregel für Ablageorte** | `storage/store.py:317-319` (`read_site_file`) und `incoming.py:58-60` (`folder_path_error`), dazu `_safe_path` (`storage/store.py:209-219`) für JSON | **Verhalten weicht ab (geprüft):** `folder_path_error` lehnt „a//b“ und „a/“ als „nicht relativ“ ab, `read_site_file` normalisiert sie. Der Docstring von `folder_path_error` behauptet „Es gelten die Pfadregeln von `Store.read_site_file`“ |
| D13 | **Jahr im Bereich prüfen und melden** | `documents.py:88-91` (`_year_problem`), `web.py:26-33` (`year_of(in_range=…)`), `prefill.py:46-49`, `modules/work/trip_pages.py:48-51`; der Text „Steuerjahr: Jahr zwischen …“ steht zweimal (`documents.py:91`, `modules/work/pages.py:43`) | gleiche Regel, die Konstanten liegen schon zentral (`defaults.py`). Nach `6ad2191` ist das Parsen vereinheitlicht, die Bereichsprüfung noch nicht |
| D14 | **Fehlertexte, die Grenzen der Modelle wiederholen** | `modules/work/pages.py:42-53`: „0 bis 1000 km“ (Modell: `entries.py:52`, `:58`), „0 bis 366“ (`MAX_ABSENCE_DAYS`, `entries.py:28`), „200 Zeichen“ (`TEXT_MAX`, `entries.py:23`) | laufen auseinander, sobald eine Grenze sich ändert; nur `MAX_WORKDAYS` wird eingesetzt (`:44`) |
| D15 | **„Formular → Modell → Hinweise je Feld aus `ValidationError`“** | `issuer_pages.py:39-42`, `:66-84`; `expected_documents_pages.py:31-36`, `:49-69`; `modules/work/pages.py:42-75`, `:81-121` | gleiches Muster dreimal, je mit eigener `HINTS`-Tabelle |
| D16 | **Abweisungsgründe als Text/Liste** | `_reasons` in `issuer_pages.py:132`, `expected_documents_pages.py:149`, `modules/work/pages.py:230`; `" ".join(result.reasons.values())` an 9 Stellen (`app.py:161`, `:174`, `proposals.py:104`, `:221`, `site_pages.py:182`, `:207`, `modules/tax_year/pages.py:144`, `modules/work/trip_pages.py:72`, …) | trivial, aber dreimal als eigene Funktion |
| D17 | **„nur auslesen, nicht einlesen“** | `modules/tax_year/assessment.py:102-103` (`_no_read_in`) und `modules/work/trip_reading.py:84` (Lambda) | `DocumentKind.read_in` könnte optional sein |
| D18 | **Bezeichnung „Anlage N Nr. …, …“** | `modules/tax_year/comparison.py:86`, `:249`, `:353` | gehört an `FormField` |
| D19 | **Werte-Schlüssel von Arbeit doppelt als Text** | `modules/work/values.py:41-53` und `modules/tax_year/anlage_n.py:33-45` | gewollt (Prinzip 2 verbietet den Import). Ein Tippfehler fällt aber erst zur Laufzeit als `UnknownValueKey` auf. Ein Test „jeder fremde Schlüssel steht im Wertekatalog“ würde das abdecken |
| D20 | **Rechenweg der Dienstreisen** | `modules/work/values.py:191-204` und `:214-232` | Prüfung „keine Reisen und nicht bestätigt“, Bezeichnung je Reise und „bestätigt, es gab keine“ sind kopiert |

### 3.2 Datenebene kennt Routen oder Modulbegriffe (Prinzip 1)

- `values/engine.py:220`: `href="/belege"` im Befund „Dateien im Eingang“.
- `expected_documents.py:16` (`HREF = "/belege/erwartet"`) und `web.py:41` (`f"/belege/erwartet/{id}"`) stehen neben `links.py`, das nur Dokument und Aussteller kennt (`links.py:4-10`).
- `incoming.py:130-133` und `:150-151`: `Row.preview_url` und `HiddenFileRow.preview_url` bauen `/dokumente/{id}/datei` und `/belege/datei/{sha}`, dasselbe noch einmal in `document_list.py:233`.
- `document_list.py:35-41` (`REFERENCE_LABELS`): Die Belege-Seite nennt die Arten `ProtocolReading` und `WageTaxCertificate` aus zwei Modulen beim Namen. Eine neue Einlesung eines Moduls erscheint dort als roher Klassenname. Die Bezeichnung gehört an die Eintragsart (`EntryKind`) oder in die Modulanmeldung.
- `registration.py:6` und `:41`: Der Vertrag der Datenebene hängt an `fastapi.APIRouter`. Das ist bewusst so, denn die Anmeldung nennt die Seiten. Es heißt aber, dass `values/engine.py` über `registration` FastAPI lädt.
- Befunde tragen grundsätzlich ein `href` (`values/findings.py:49`). Dass die Datenebene Links kennt, ist also angelegt. Der Verstoß liegt darin, dass die Links an verschiedenen Stellen gebaut werden statt nur in `links.py`.
- Auch Fachkerne der Module bauen ihre eigenen Adressen: `modules/work/values.py:268`, `:275`; `modules/tax_year/comparison.py:77-80`, `:213-214`. Das ist innerhalb des Moduls, aber nach Prinzip 1 Wissen der Anbindung.

### 3.3 Module kennen sich nicht (Prinzip 2)

- **Kein Import zwischen den Modulen** (geprüft mit `grep` über beide Pakete). Das Steuerjahr liest Arbeit nur über Ausgewiesene Werte (`calculation.use`, `modules/tax_year/anlage_n.py:311`, `:380`).
- Arbeit liest Vorschläge über `store_of(request).state()` statt über `ModuleState` (`modules/work/trip_view.py:83`, `trip_pages.py:124`). Das ist kein Verstoß gegen Prinzip 2, denn `Proposal` ist ein Baustein der Datenebene. Es umgeht aber die Eingrenzung auf den Nutzer, die `ModuleState` bietet (`registration.py:72-82` filtert den Eigentümer, `proposals_of` filtert nach dem Eigentümer des Dokuments). Eine Methode `ModuleState.latest_proposal(document)` würde zugleich D3 beheben.

### 3.4 Invarianten nur vor `apply` (Prinzip 3)

Alle fünf sind mit einem echten `Store` geprüft (3.6): `apply` nimmt die Änderung an.

| Nr. | Invariante | Nur geprüft in | Folge, wenn ein anderer Schreibweg sie umgeht |
|---|---|---|---|
| I1 | Eine Datei (SHA-256) höchstens einmal je Nutzer als Dokument | `documents.py:173` (`_already_taken_in` auf `store.state()`), Seite `site_pages.py:130` | zwei Dokumente derselben Datei. Zwei gleichzeitige Klicks auf „Aufnehmen“ reichen dafür, denn die Prüfung läuft vor dem Lock von `apply` (`storage/store.py:416-418`) |
| I2 | Ein Ordner höchstens einmal ausgeblendet | `incoming.py:69` | doppelte Ausblendung. „Wieder einblenden“ löscht nur eine (`site_pages.py:225`), der Ordner bleibt also ausgeblendet |
| I3 | Erwarteter Beleg nur für eine bekannte Dokumentart mit Bezugszeitraum | `expected_documents_pages.py:53` | Erwarteter Beleg, der nie erfüllt werden kann, und ein Befund „ausstehend“ jedes Jahr |
| I4 | Eingabe passt zum Feld (`TypedInput.check`) | `modules/tax_year/inputs.py:30`; der Docstring von `FormInput` (`modules/tax_year/entries.py:56-61`) nennt das ausdrücklich „Vorgang in `inputs`“, aber `check_input` (`:68-78`) prüft nur die Eindeutigkeit | `FormInput(content="viele")` für Nr. 58 wird angenommen, danach wirft `compute_homeoffice_days` `ValueError` bei `int(entry.content)` (`modules/tax_year/anlage_n.py:348`). Die Befundliste und die Seite Anlage N brechen ab |
| I5 | Name und „Privatperson“ des eigenen Ausstellers ändern sich nur über die Angaben zur Person (ADR 0009) | `issuer_pages.py:234` (`locked`) | Der Aussteller lässt sich umbenennen und `private_person=False` setzen. Dann fehlt der Name in der abgeleiteten Sperrliste (`storage/issuers.py:56-58`), ein Datenschutzrisiko |

Dazu zwei Prüfungen auf einem älteren Stand, die der Schreibweg nicht wiederholt:
- `documents.py:230`: Art und Jahr sind gesperrt, „wenn etwas am Dokument hängt“. Entsteht zwischen dieser Prüfung und `apply` ein Vorschlag (Auslesen in einem zweiten Tab), wird die Art trotzdem geändert.
- `issuer_pages.py:255`: Den eigenen Aussteller löschen ist gesperrt. Das ist harmlos, denn `_reference_problems` (`storage/store.py:193-206`) sperrt ohnehin über den Verweis aus `PersonalDetails.issuer`. Die Prüfung dient hier nur der besseren Meldung.

Positiv: `TripsConfirmation` (`modules/work/entries.py:137-153`), `Place` (`places.py:53-60`), `FormInput`-Eindeutigkeit, `PersonalDetails` (`storage/personal_details.py:40-54`), Aussteller-Namen (`storage/issuers.py:95-98`) und „ein Dokument je Bezugszeitraum“ (`storage/documents.py:84-99`) prüft der Schreibweg. Die Seite prüft dort nur zusätzlich für die Meldung (etwa `trip_pages.py:101`).

### 3.5 Logik in Route-Handlern und Vorlagen (Prinzip 4)

- `modules/tax_year/pages.py:88-119`: Die Route baut Zeilenwerte, `frozen` (`:98-105`) und `inputs` (`:115-119`) selbst zusammen. Das ist kein Rechnen, aber eine Zuordnung von Schnappschuss und Feld, die in `comparison.py` neben `describe_frozen` gehört.
- `site_pages.py:162-170`: Die Entscheidung, wohin es nach dem Aufnehmen weitergeht (Einlesung, Reiter Dokumente oder nächste Datei), steht im Handler. Das ist vertretbar, denn es ist Navigation.
- `issuer_pages.py:240-245`: Nach einer Abweisung sucht der Handler selbst, wer den Namen schon trägt. Die Logik steht schon in `resolve_issuer`/`holder_of_name` (`issuer_field.py:62-64`).
- `modules/work/trip_view.py:122`: `total_km` wird in der Ansicht summiert, während `compute_travel_fare` dieselbe Summe rechnet (`modules/work/values.py:224-230`). `trip_view.py:126` liefert `fare` ohnehin aus den Werten, `total_km` ließe sich aus dessen Rechenweg ablesen.
- `app.py:139-147`: Den Befund zum Ausblenden sucht die Route in der Befundliste. Das passt zu Prinzip 3, denn so wird auf dem aktuellen Stand geprüft. Es gehört aber zu `dismissals.py`.
- Vorlagen sind dünn (`grep` nach `|sum`, `namespace`, Rechnungen in `set`: keine Treffer). Nur `work/_trips.html:6` formatiert den km-Satz selbst (`rate | string | replace(".", ",")`), parallel zu `modules/work/values.py:234`.

### 3.6 Geprüft mit `uv run`

Die Skripte lagen außerhalb des Repos; sie sind kurz und lassen sich nachbauen.

```text
parse_cents vs parse_german_number
'1.234,56' -> 123456 | 1234.56     '12.5' -> 12500 | None      '1.2.3' -> 12300 | None
'1e3'      -> 100000 | None        '5 €'  -> ValueError | 5    '007'   -> 700 | 7
Aussteller-Suche: ''  Katalog: alle   Feld: keine
                  'Musterfirma GmbH Niederlassung'  Katalog: []  Feld: ['Musterfirma GmbH']
folder_path_error: 'a//b' und 'a/' -> „nicht relativ“; './a' -> „gibt es nicht“
incoming_files vs site_rows (3000 Zufallsfälle): 0 Abweichungen
trip_reading.statements mit taken_in_at None und gesetzt: TypeError
Store.apply (leeres Datenverzeichnis, echte Modulanmeldungen):
  zwei Dokumente gleicher SHA-256: Applied
  Ordner zweimal ausgeblendet: Applied
  Erwarteter Beleg mit unbekannter Dokumentart: Applied
  FormInput 'viele' für E0204507: Applied -> Values.get(...n_homeoffice_days) -> ValueError
  eigener Aussteller umbenannt, private_person=False: Applied
```

---

## 4. Große Dateien (über 300 Zeilen)

| Datei | Zeilen | Befund | Naht | Empfehlung |
|---|---|---|---|---|
| `storage/store.py` | 699 | Vier Aufgaben: Ablageorte lesen (`:52-70`, `:252-284`, `:312-365`: `SiteFile`, `site_folder`, `_load_sites`, `read_site_file`, `list_site_files` mit SHA-Zwischenspeicher), laden (`:370-412`), Schreibweg (`:414-628`) und abgeleitete Sperrliste (`:642-660`) | **Ablageorte** sind eine eigene, nur lesende Fähigkeit mit eigener Fehlerklasse (`SiteFileError`), eigener Pfadregel (siehe D12) und eigenem Zwischenspeicher. Als `storage/sites.py` mit einer kleinen Schnittstelle (`names()`, `list(site)`, `read(site, path)`) wäre das ein tiefer Baustein, und D12 hätte ein Zuhause | **Schnitt lohnt** (S-M). Schreibweg, Laden und Sperrliste bleiben zusammen in `Store`: Sie teilen `_file_checksums` und `_kinds`, die Schnittstelle (`state()`, `apply()`, `references_to()`) ist schon klein, und der Teil ist tief |
| `modules/tax_year/anlage_n.py` | 431 | Feldkatalog 2025 (`:82-288`, davon gut 100 Zeilen Argumentlisten `_catalog_field`/`_known`/`_computed`, `:82-169`) und Zuordnung der Werte (`:291-431`) | Katalog (Daten) und Zuordnung (Rechnen) | **Kleiner Schnitt lohnt** (S): `_known` und `_computed` unterscheiden sich nur in `computed=` und im Schlüssel, also ein Helfer statt drei. Den Katalog als `fields_2025.py` herauszulösen, wird sinnvoll, sobald 2026 dazukommt; heute ist es optional |
| `modules/work/values.py` | 408 | Vier unabhängige Wertgruppen (Tätigkeitsstätte `:56-105`, Arbeitsmittel `:108-131`, Lohnsteuerbescheinigung `:134-175`, Dienstreisen `:178-246`), Befunde (`:249-277`) und 128 Zeilen Deklaration `VALUES` (`:280-408`) | dieselbe Naht wie in 2.1; jede Gruppe mit ihren `ValueDefinition`s | **Schnitt folgt der Modulentscheidung** (#134). Werden Dienstreisen oder die Lohnsteuerbescheinigung abgespalten, zerfällt die Datei von selbst. Sonst lohnt nur D20 |
| `modules/tax_year/comparison.py` | 401 | Drei Abgleiche: Protokoll (`:59-210`), Schnappschuss (`:213-262`, `:378-401`) und Bescheid (`:265-359`) | je Abgleich eine Datei; gemeinsam sind nur `_taken_order` und `latest_snapshot` | **Schnitt lohnt** (S): `protocol_check.py`, `snapshot_check.py`, `assessment_check.py` (Namen offen). `module_findings` (`:362-375`) bleibt als Sammelstelle. Die Schnittstelle nach außen (`module_findings`, `snapshot_on_filing`, `current_assessment`, `latest_snapshot`, `describe_frozen`) bleibt gleich |
| `values/model.py` | 369 | Werttypen (`Amount`, `Period`, Fundstellen, `ValueRef`, Ergebnisse) und deutsches Formatieren und Parsen (`:40-71`) | Formatieren und Parsen könnten in eine eigene Datei `values/german.py` | **Kein Schnitt nötig.** Die Datei besteht aus Datentypen mit wenig Logik. Das Parsen gehört trotzdem an eine Stelle (D1) |
| `modules/work/pages.py` | 351 | allgemeines CRUD für Nutzereingaben (`EntryForm`, `:124-351`), Formular-Bau (`:57-121`) und Übersicht `/arbeit` mit eingebetteten Dienstreisen (`:235-253`) | `EntryForm` samt `build_*` ist ein wiederverwendbarer Baustein für „Eintragsart mit Formular“ | **Schnitt optional** (M). Wird `EntryForm` für D15 verallgemeinert (Aussteller, Erwarteter Beleg, Arbeit), wandert es aus Arbeit heraus in die Anbindung. Sonst ist die Datei ordentlich |
| `values/snapshots.py` | 335 | einfrieren und auftauen (`:49-153`), vergleichen (`:155-298`), Befund (`:315-335`) | einfrieren und vergleichen | **Kein Schnitt nötig,** eine Aufgabe (Schnappschuss) mit kleiner Schnittstelle (`freeze`, `compare`, `latest_snapshots`, `snapshot_findings`) |
| knapp darunter: `incoming.py` (295), `extraction.py` (271), `proposals.py` (265), `issuer_pages.py` (260), `trips.py` (253), `documents.py` (253) | | `incoming.py` muss wegen der Mischung aus 1.1 geteilt werden. `trips.py` und `extraction.py` sind tief (reiner Kern mit wenigen öffentlichen Funktionen) und bleiben | | |

`modules/work/trips.py`, `trip_reading.py` und `places.py` gehören zu den tiefsten Bausteinen im Code: Sie sind rein, haben wenige öffentliche Funktionen (`plan_changes`, `confirm_changes`, `proposed_trips`, `take_over_changes`, `locate_changes` …) und viel Verhalten dahinter. Sie zu teilen, brächte nichts.

---

## 5. Kurzliste: Aufräum-Kandidaten

Nach Nutzen pro Aufwand gereiht. **#134** heißt: hängt an der Entscheidung zum Zuschnitt der Module bzw. der Bausteine.

| Rang | Kandidat | Aufwand | Nutzen | #134? |
|---|---|---|---|---|
| 1 | **Invarianten in den Schreibweg** (3.4, I1-I5): `check` an `Document` (SHA je Nutzer), `HiddenFolder` (eindeutig), `ExpectedDocument` (Art mit Bezugszeitraum, über `once_per_period`-ähnliche Übergabe aus den Modulanmeldungen), `FormInput` (Inhalt gegen `TypedInput`, über eine von der Modulanmeldung gelieferte Prüfung) und eigener Aussteller (Name und Privatperson nur zusammen mit `PersonalDetails` änderbar) | M | hoch: behebt einen Absturz (I4), ein Datenschutzrisiko (I5) und eine Wettlaufsituation (I1) | nein |
| 2 | **Ein Betrags-Parser** (D1): `parse_cents` durch `parse_german_number` ersetzen (Cent-Umrechnung wie in `modules/work/reading.py:37-42`), Test mit „12.5“ | S | hoch: verhindert still falsche Beträge | nein |
| 3 | **Alle Adressen in `links.py`** (3.2): `/belege`, `/belege/erwartet[/id]`, beide Datei-Routen, Bezeichnungen der verweisenden Arten an die Eintragsart statt in `REFERENCE_LABELS`; dazu ein Import-Test „`storage/` und `values/` enthalten kein `"/` + Route“ | S | mittel: Prinzip 1 wird prüfbar, Umbenennen von Routen wird sicher | nein |
| 4 | **Gemischte flache Dateien teilen** (1.1, Option C): `incoming.py` (Eingang und Ausblenden / Seitenmodell der Ablage), `issuer_field.py` (Kern / Route), `document_list.py` (Zustand, Filter, Formularwahl / Reiter); Befundliste-Routen aus `app.py`; `issuers.py` zu den Aussteller-Bausteinen | S-M | mittel: Voraussetzung für jede Paketordnung und für einen Import-Test „Datenebene importiert kein `fastapi`“ | nein (Ziel-Paket hängt an #134) |
| 5 | **Vorschlag und Vorlage einmal** (D3, D4): `latest_proposal(state, document)` und `template_of(kinds, document)` in `proposals.py`, `ModuleState.latest_proposal` statt `store_of(request)` in Arbeit (3.3) | S | mittel: fünf bis sieben Stellen weniger, Arbeit liest nur noch über `ModuleState` | nein |
| 6 | **ELSTER-Kopf einmal prüfen** (D5): `parse_elster_document(document, content, belegart, title)` in `elster_html.py`, `ParsedProtocol` entfällt | S | mittel | leicht: Wandert die Lohnsteuerbescheinigung ins Steuerjahr, wandert `elster_html.py` mit |
| 7 | **`comparison.py` dreiteilen** (4) und dabei D6, D18 und doppeltes `MODULE_KEY` / Protokoll-Adresse (2.2) beheben | S | mittel: Lokalität im Steuerjahr | nein |
| 8 | **Ablageorte aus `Store` lösen** (4): `storage/sites.py` mit einer Pfadregel (D12) und `folder_path_error` darauf aufbauend; `incoming_files` auf `site_rows` zurückführen (D11) | M | mittel: ein tiefer Baustein mehr, eine Pfadregel statt zwei | nein |
| 9 | **Kleine Dubletten in Arbeit** (D2, D14, D20): `trips_of`/`confirmations_of` auf die Funktionen aus `values.py` gründen, `HINTS` aus den Modellgrenzen bilden, Rechenweg der Dienstreisen einmal | S | gering bis mittel | ja: bei Abspaltung der Dienstreisen gleich mit erledigen |
| 10 | **Formular-Muster einmal** (D15, D16, D8): `EntryForm` aus `modules/work/pages.py` verallgemeinern (Formular → Modell → Hinweise), `rejection_text(result)`, `entry_of(state, kind, id, owner)` | M | mittel: drei Seiten-Dateien schrumpfen | nein |
| 11 | **Dienstreisen (mit Orten, `place_search.py`) als eigenes Modul** oder als Unterpaket von Arbeit (2.1) | L (Modul, mit Migration und Schlüsselwechsel) / S (Unterpaket) | mittel: Arbeit wird zur Hälfte so groß, die Kopplung der Übersicht wird sichtbar | **ja** |
| 12 | **Lohnsteuerbescheinigung umhängen** (ins Steuerjahr oder eigenes Modul) (2.1) | M-L | gering bis mittel | **ja** |
| 13 | **Ein Weg für Nutzereingaben** (2.2): `FormInput` im Steuerjahr gegen eigene Eintragsarten in Arbeit abwägen | M-L | mittel (Prinzip 7) | **ja** |
| 14 | **Bausteine mit Anmeldung** (2.3, Option 2): Belege und Aussteller melden Router und Befunde an, statt in `app.py:95-102` und `values/engine.py:195-223` namentlich verdrahtet zu sein | M | mittel | **ja** |
| 15 | **Test für fremde Werte-Schlüssel** (D19): Jeder Schlüssel, den ein Modul per `calculation.use` anfragt, steht im Wertekatalog | S | gering (Sicherheitsnetz) | nein |

Für die Slices schlage ich als Reihenfolge vor: 2 → 1 → 3 → 4 → 5/6/7 sind unabhängig von #134 und machen die Entscheidung dort leichter, weil die Dateien danach schon nach Schicht getrennt sind. 11-14 folgen aus #134.
