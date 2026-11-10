# Adressen: Art plus zufällige Kennung, ohne Modul

Jeder Eintrag wird überall mit derselben Adresse `<Art>:<Kennung>` genannt, z. B. `Property:7KQ2M9XA4T`. Die Kennung wird beim Anlegen zufällig erzeugt, ist global eindeutig, trägt keine Bedeutung und ändert sich nie, auch nicht durch Migrationen. Die Art ist der Name der Klasse, die das Modul für den Eintrag baut. Sie ist über alle Module eindeutig, das prüft der Testkern. Das Modul, dem eine Art gehört, steht in der Modulanmeldung und nicht in der Adresse, denn so behält ein Eintrag seine Adresse, wenn er in ein anderes Modul wandert. Der Nutzer steht nicht in der Adresse, weil der Eintrag selbst weiß, wem er gehört.

Verworfen: lesbare Kurznamen aus dem Inhalt (veralten beim Umbenennen und tragen sensible Daten in URLs, Protokolle und git), fortlaufende Nummern je Art (kollidieren über Nutzer und Migrationen hinweg) und ein Modulpräfix in der Adresse (bindet den Eintrag an seinen heutigen Ort).

Zusammengeführte Einträge (z. B. Aussteller) hinterlassen dauerhaft einen Alias „alte Kennung → neue“. Benennt man eine Art um, schreibt die Migration beim Start alle Adressen in Arbeitsdaten um; einen Art-Alias gibt es nur, solange ein Schnappschuss die alte Art enthält (wie bei Schlüsseln, siehe [ADR 0004](0004-migration-beim-start.md)). Siehe [Kennungen und Verweise auf Einträge](https://github.com/oiff2/MoarCoal/issues/20).
