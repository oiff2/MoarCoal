# Recherche: Arbeitsmittel über der GWG-Grenze (AfA)

Zu [#156](https://github.com/oiff2/MoarCoal/issues/156). Geprüft wird die Rechtslage, nach der MoarCoal die „Summe der Arbeitsmittel“ eines Jahrs bildet. Stand der Recherche: 20.11.2026.

**Ergebnis: die Arbeitsgrundlage des Tickets ist bestätigt.** Offen geblieben ist nur, ob die Grenze bei 7 % Umsatzsteuer niedriger liegt (siehe „Vereinfachungen“). Bei einem Jahr Nutzungsdauer wird der volle Betrag im Jahr der Anschaffung angesetzt (BMF, Rz. 1.4).

## Aussagen und Quellen

### Arbeitsmittel sind Werbungskosten, über AfA verteilt

> „Aufwendungen für Arbeitsmittel, zum Beispiel für Werkzeuge und typische Berufskleidung. Nummer 7 bleibt unberührt;“
>
> „Absetzungen für Abnutzung und für Substanzverringerung, Sonderabschreibungen nach § 7b und erhöhte Absetzungen. § 6 Absatz 2 Satz 1 bis 3 ist in Fällen der Anschaffung oder Herstellung von Wirtschaftsgütern entsprechend anzuwenden.“

Quelle: § 9 Abs. 1 Satz 3 Nr. 6 und 7 EStG, <https://www.gesetze-im-internet.de/estg/__9.html>.

### GWG-Grenze 800 € ohne Umsatzsteuer

> „Anschaffungs- oder Herstellungskosten, vermindert um einen darin enthaltenen Vorsteuerbetrag (§ 9b Absatz 1), […] für das einzelne Wirtschaftsgut 800 Euro nicht übersteigen.“

Quelle: § 6 Abs. 2 Satz 1 EStG, <https://www.gesetze-im-internet.de/estg/__6.html>. Gilt in dieser Höhe für Anschaffungen ab 2018 (vorher 410 €). Eine geplante Anhebung im Wachstumschancengesetz kam nicht; auch für 2026 bleibt es bei 800 € (Übersichten, z. B. <https://www.finanztip.de/geringwertige-wirtschaftsgueter/>, <https://rechner-hub.de/gwg-rechner/gwg-grenzen-2026/>).

Arbeitnehmer haben keinen Vorsteuerabzug; die Grenze gilt trotzdem ohne Umsatzsteuer (R 9.12 LStR, laut <https://www.steuertipps.de/lexikon/a/arbeitsmittel>; den amtlichen Wortlaut konnte ich nicht abrufen, lsth.bundesfinanzministerium.de war nicht erreichbar). Mit 19 % Umsatzsteuer sind das **952,00 € brutto**. MoarCoal speichert den Bruttobetrag und vergleicht mit 952,00 €.

### Lineare AfA, im ersten Jahr monatsgenau

> „ist jeweils für ein Jahr der Teil der Anschaffungs- oder Herstellungskosten abzusetzen, der bei gleichmäßiger Verteilung dieser Kosten auf die Gesamtdauer der Verwendung oder Nutzung auf ein Jahr entfällt“ (Satz 1)
>
> „Die Absetzung bemisst sich hierbei nach der betriebsgewöhnlichen Nutzungsdauer des Wirtschaftsguts.“ (Satz 2)
>
> „Im Jahr der Anschaffung oder Herstellung des Wirtschaftsguts vermindert sich für dieses Jahr der Absetzungsbetrag nach Satz 1 um jeweils ein Zwölftel für jeden vollen Monat, der dem Monat der Anschaffung oder Herstellung vorangeht.“ (Satz 4)

Quelle: § 7 Abs. 1 EStG, <https://www.gesetze-im-internet.de/estg/__7.html>.

Der Monat der Anschaffung zählt also mit: Anschaffung im März ergibt 10 Monate im ersten Jahr. Bei *n* Jahren Nutzungsdauer verteilt sich der Betrag auf 12 · *n* Monate; das letzte Jahr nimmt die restlichen Monate.

### Computerhardware und Software: ein Jahr, voller Betrag im Jahr der Anschaffung

> „Für die nach § 7 Absatz 1 EStG anzusetzende Nutzungsdauer kann für die in Rz. 2 ff. aufgeführten materiellen Wirtschaftsgüter ‚Computerhardware‘ sowie die in Rz. 5 näher bezeichneten immateriellen Wirtschaftsgüter ‚Betriebs- und Anwendersoftware‘ eine betriebsgewöhnliche Nutzungsdauer von einem Jahr zugrunde gelegt werden.“ (Rz. 1)
>
> „Die Regelung findet gemäß § 9 Absatz 1 Satz 3 Nummer 7 Satz 1 EStG auch für Überschusseinkünfte Anwendung.“ (Rz. 1.3)
>
> „Es wird nicht beanstandet, wenn abweichend zu § 7 Absatz 1 Satz 4 EStG die Abschreibung im Jahr der Anschaffung oder Herstellung in voller Höhe vorgenommen wird.“ (Rz. 1.4)

Quelle: BMF-Schreiben vom 22.02.2022, „Nutzungsdauer von Computerhardware und Software zur Dateneingabe und -verarbeitung“, GZ IV C 3 - S 2190/21/10002 :025, DOK 2022/0186479 (ersetzt das Schreiben vom 26.02.2021). Gelesen als PDF über <https://www.steuerschroeder.de/blog/wp-content/uploads/2022/02/Nutzungsdauer-von-Computerhardware-und-Software-zur-Dateneingabe-und-verarbeitung.pdf>; die Seite des BMF war nicht erreichbar. Für Privatvermögen, das zur Einkünfteerzielung dient (Arbeitsmittel), gilt es ab 2021 (Rz. 7).

## Daraus folgt für MoarCoal

- Bis zur GWG-Grenze des Anschaffungsjahrs (952,00 € brutto): voller Betrag im Steuerjahr der Anschaffung, eine Nutzungsdauer braucht es nicht.
- Darüber: Nutzungsdauer in ganzen Jahren ist Pflicht, das Datum der Anschaffung muss im Steuerjahr liegen. AfA linear, im ersten Jahr ab dem Monat der Anschaffung (13 − Monat von 12 · *n* Monaten), danach 12 Monate je Jahr, im letzten Jahr der Rest.
- Gerechnet wird mit dem Baustein `values/depreciation.py` der Datenebene (für jedes Modul gleich, z. B. später Gebäude mit Prozentsatz als Monate). Cent-Rundung: Die bis zum Ende eines Jahrs aufgelaufene AfA ist Betrag · Monate bis dahin / (12 · *n*), kaufmännisch auf Cent gerundet; die AfA des Jahrs ist der Unterschied zum Vorjahr. So ergibt die Summe aller Jahre genau den Anschaffungsbetrag. Beispiel (erfunden): Schreibtisch 1.200,00 €, März 2025, 3 Jahre → 2025: 333,33 € (10/36), 2026: 400,00 €, 2027: 400,00 €, 2028: 66,67 €.
- Nutzungsdauer ein Jahr: voller Betrag im Jahr der Anschaffung (Rz. 1.4), für Anschaffungen ab 2021 (Rz. 7).
- Die Grenze steht je Steuerjahr in einer Tabelle (`workplace/depreciation.py`, geprüft 2018 bis 2026). Für ein Jahr ohne Eintrag gibt es keine Fortschreibung: Eine Anschaffung, die nach Betrag nicht sicher zuzuordnen ist, macht den Wert noch nicht berechenbar („GWG-Grenze für <Jahr> noch nicht geprüft“). Sicher ist nur ein Jahr nach der Tabelle mit einem Betrag bis zur zuletzt geprüften Grenze; das ist GWG, weil die Grenze nicht sinkt, und der Rechenweg nennt es. Jahre vor der Tabelle bleiben ganz offen, weil für sie nichts Neues erfasst wird. Neues Jahr: Grenze prüfen, mit Quelle hier und in der Tabelle nachtragen.

## Vereinfachungen

- **7 % Umsatzsteuer:** Gilt die Grenze ohne Umsatzsteuer, liegt sie bei 7 % (z. B. Fachbücher) bei 856,00 € brutto. MoarCoal kennt den Steuersatz nicht und vergleicht immer mit 952,00 €. Eine Anschaffung zwischen 856,00 € und 952,00 € mit 7 % würde also zu Unrecht sofort abgesetzt. Bleibt bis auf Weiteres so; Abhilfe wäre ein Feld für den Steuersatz.
- **Ein Jahr Nutzungsdauer:** Rz. 1.4 gilt nur für Computerhardware und Software. MoarCoal unterscheidet nicht nach Art (keine AfA-Tabelle, Ticket) und setzt bei einem Jahr ab 2021 immer den vollen Betrag im Anschaffungsjahr an (Rz. 7); davor wird auch ein Jahr monatsgenau verteilt. Für anderes Arbeitsmittel ist ein Jahr Nutzungsdauer kaum denkbar.
- **Nutzungsdauer bis zur Grenze:** Eine dort eingetragene Nutzungsdauer wird gespeichert, zählt aber nicht und erscheint auf der Seite nicht.
- Nicht gebaut (Ticket, außerhalb): anteilige private Nutzung, Sammelposten, degressive AfA, Verkauf oder Ausscheiden vor Ende der Nutzungsdauer, Arbeitsmittel, die erst später zum Arbeitsmittel werden.
