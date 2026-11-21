"""Anlage V: bisher nur ihre Struktur aus gespeicherten Seiten von Mein ELSTER; berechnet wird
noch kein Feld, deshalb hat sie keinen Katalog."""

from moarcoal.modules.tax_year.anlagen import Anlage
from moarcoal.modules.tax_year.structure import load_structure

FORM = "V"

ANLAGE_V = Anlage(FORM, {}, {2025: load_structure(FORM, 2025)})
