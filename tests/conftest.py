from collections.abc import Callable

import httpx
import pytest

from moarcoal.modules.tax_year.anlage_n import FORMS, STRUCTURES
from moarcoal.modules.tax_year.structure import form_pages


@pytest.fixture
def anlage_n_text() -> Callable[[httpx.Client], str]:
    """Der Text aller Unterseiten der Anlage N 2025, hintereinander."""

    def read(http: httpx.Client) -> str:
        pages = form_pages(STRUCTURES[2025], FORMS[2025])
        return "".join(http.get(f"/steuerjahr/anlage-n/2025/{p.slug}").text for p in pages)

    return read
