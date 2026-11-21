"""Prüfungen von Identifikationsnummer (Prüfziffer) und IBAN (Prüfsumme); reine Funktionen.

Die Prüfungen laufen im Schreibweg (`EntryKind.check` der Angaben zur Person); die Seite ruft
dieselben Funktionen, um den Grund vorab zu nennen.
"""

import re

ID_NUMBER_LENGTH = 11
IBAN_MIN_LENGTH = 15
IBAN_MAX_LENGTH = 34


def normalize_id_number(text: str) -> str:
    """Die Identifikationsnummer ohne Leerzeichen."""
    return re.sub(r"\s+", "", text)


def normalize_iban(text: str) -> str:
    """Die IBAN ohne Leerzeichen, in Großbuchstaben."""
    return re.sub(r"\s+", "", text).upper()


def _check_digit(first_ten: str) -> int:
    """Prüfziffer nach ISO 7064, MOD 11,10 (Verfahren der Identifikationsnummer)."""
    product = 10
    for char in first_ten:
        total = (int(char) + product) % 10
        product = ((total or 10) * 2) % 11
    digit = 11 - product
    return 0 if digit == 10 else digit


def id_number_problem(text: str) -> str | None:
    """Warum `text` (normalisiert) keine Identifikationsnummer ist; `None`, wenn sie stimmt.

    Geprüft werden elf Ziffern, keine führende Null und die Prüfziffer; die weiteren Regeln der
    Vergabe (Ziffernverteilung) prüft MoarCoal nicht.
    """
    if not re.fullmatch(rf"\d{{{ID_NUMBER_LENGTH}}}", text):
        return "Identifikationsnummer: elf Ziffern"
    if text.startswith("0"):
        return "Identifikationsnummer: beginnt nicht mit 0"
    if _check_digit(text[:-1]) != int(text[-1]):
        return "Identifikationsnummer: Prüfziffer stimmt nicht"
    return None


def iban_problem(text: str) -> str | None:
    """Warum `text` (normalisiert) keine gültige IBAN ist; `None`, wenn die Prüfsumme stimmt."""
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", text) or not (
        IBAN_MIN_LENGTH <= len(text) <= IBAN_MAX_LENGTH
    ):
        return "IBAN: Länderkennung, zwei Prüfziffern und die Kontonummer, 15 bis 34 Zeichen"
    moved = text[4:] + text[:4]
    if int("".join(str(int(char, 36)) for char in moved)) % 97 != 1:
        return "IBAN: Prüfsumme stimmt nicht"
    return None
