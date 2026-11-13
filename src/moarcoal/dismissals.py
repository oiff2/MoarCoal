"""Ausblenden und Einblenden eines Befunds (docs/grundgeruest.md, 3.2 und 3.5)."""

import datetime

from moarcoal.storage import Applied, Delete, Dismissal, Put, Rejected, Store
from moarcoal.values.findings import Finding


class NoteMissing(Exception):
    """Ausblenden ohne Notiz: die Notiz ist Pflicht."""


def dismiss(
    store: Store, user: str, finding: Finding, note: str, today: datetime.date
) -> Applied | Rejected:
    """Blendet den Befund für `user` aus; gilt, solange sein Fingerabdruck gleich bleibt."""
    text = note.strip()
    if not text:
        raise NoteMissing
    kind, target = finding.identity
    entry = Dismissal(
        owner=user,
        finding_kind=kind,
        target=target,
        fingerprint=finding.fingerprint,
        note=text,
        noted_on=today,
    )
    return store.apply([Put(entry)])


def undismiss(store: Store, user: str, dismissal_id: str) -> Applied | Rejected | None:
    """Löscht die Ausblendung; `None`, wenn `user` keine mit dieser Kennung hat."""
    state = store.state()
    found = next(
        (d for d in state.of_kind(Dismissal) if d.id == dismissal_id and d.owner == user), None
    )
    if found is None:
        return None
    return store.apply([Delete(found.address, expected=state.checksum(found.address) or "")])
