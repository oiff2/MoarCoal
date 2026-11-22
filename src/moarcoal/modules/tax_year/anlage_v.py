"""Anlage V: bisher nur ihre Struktur aus gespeicherten Seiten von Mein ELSTER; berechnet wird
noch kein Feld, deshalb ist ihr Katalog leer (die Struktur 2025 lädt die Anlage trotzdem)."""

from moarcoal.modules.tax_year.anlagen import Anlage

FORM = "V"

ANLAGE_V = Anlage(FORM, {2025: ()}, all_structure_fields=True)
