"""Link eines Befunds: baut die Anbindung aus `href`, Befundart, Verweisen oder Ziel (#154)."""

from moarcoal.expected_documents import DUPLICATE, PENDING
from moarcoal.modules import MODULES
from moarcoal.modules.work.workplace.entries import WorkEquipment
from moarcoal.storage import Document, EntryAddress, ExpectedDocument
from moarcoal.values.findings import INCOMING_FILES, Finding, Severity
from moarcoal.web.helpers import finding_url
from moarcoal.web.links import document_url, expected_documents_url, site_url

DOCUMENT = EntryAddress(kind=Document.__name__, id="AAAAAAAAAA")
EQUIPMENT = EntryAddress(kind=WorkEquipment.__name__, id="BBBBBBBBBB")
UNKNOWN = EntryAddress(kind="Rereading", id="CCCCCCCCCC")


def finding(kind: str = "k", target: EntryAddress | str = "ziel", **more: object) -> Finding:
    return Finding(kind, Severity.NOTE, target, "Text", **more)  # pyright: ignore[reportArgumentType]


def test_a_document_target_links_to_the_document() -> None:
    assert finding_url(MODULES, finding(target=DOCUMENT)) == document_url(DOCUMENT.id)


def test_an_explicit_href_of_a_module_wins() -> None:
    assert finding_url(MODULES, finding(target=DOCUMENT, href="/arbeit?jahr=2025")) == (
        "/arbeit?jahr=2025"
    )


def test_the_first_linked_entry_with_a_page_wins() -> None:
    found = finding(target=UNKNOWN, link=(UNKNOWN, EQUIPMENT, DOCUMENT))
    assert finding_url(MODULES, found) == f"/arbeit/arbeitsmittel/{EQUIPMENT.id}"


def test_block_findings_without_an_entry_link_to_their_page() -> None:
    expected = f"{EntryAddress(kind=ExpectedDocument.__name__, id='DDDDDDDDDD')}@2025"
    assert finding_url((), finding(INCOMING_FILES, "eingang")) == site_url()
    assert finding_url((), finding(PENDING, expected)) == expected_documents_url()
    assert finding_url((), finding(DUPLICATE, expected)) == expected_documents_url()


def test_without_a_page_there_is_no_link() -> None:
    assert finding_url(MODULES, finding(target="sperrliste")) is None
    assert finding_url(MODULES, finding(target=UNKNOWN)) is None
