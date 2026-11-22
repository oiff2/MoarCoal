"""Anlage KAP: bisher nur ihre Struktur aus gespeicherten Seiten von Mein ELSTER; berechnet wird
noch kein Feld (das kommt mit dem Modul Kapitalvermögen), deshalb ist ihr Katalog leer (die
Struktur 2025 lädt die Anlage trotzdem)."""

from moarcoal.modules.tax_year.anlagen import Anlage

FORM = "KAP"

ANLAGE_KAP = Anlage(FORM, {2025: ()}, all_structure_fields=True)
