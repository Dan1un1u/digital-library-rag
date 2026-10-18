import fitz
import pytest

from dlrag.ingestion.metadata import author_names, extract_metadata
from dlrag.ingestion.errors import ProjectError


def make_paper(path, embedded=None, lines=None):
    with fitz.open() as pdf:
        p = pdf.new_page()
        for y, text, size in lines or [(80, "Evidence Search for Libraries", 20),
                                       (120, "Alice Smith and Bob Jones", 12),
                                       (150, "Published: 2024", 10),
                                       (200, "Abstract", 11),
                                       (230, "This paper studies document retrieval and grounded question answering.", 10)]:
            p.insert_text((50, y), text, fontsize=size)
        if embedded:
            pdf.set_metadata(embedded)
        pdf.save(path)
    return path


def test_embedded_metadata_takes_precedence(tmp_path):
    p = make_paper(tmp_path / "paper.pdf", {"title": "A verified embedded title", "author": "Doe, Jane; John Smith",
                                           "creationDate": "D:19990101000000"})
    result = extract_metadata(p)
    m = result["metadata"]
    assert m["title"] == "A verified embedded title" and m["authors"] == ["Doe, Jane", "John Smith"]
    assert m["year"] == 2024 and result["field_sources"]["title"]["method"] == "pdf_metadata"
    assert result["requires_confirmation"] is True


def test_title_and_authors_from_first_page(tmp_path):
    p = make_paper(tmp_path / "paper.pdf", {"title": "Untitled"})
    r = extract_metadata(p)
    assert r["metadata"]["title"] == "Evidence Search for Libraries"
    assert r["metadata"]["authors"] == ["Alice Smith", "Bob Jones"]
    assert r["metadata"]["language"] == "en"
    assert r["field_sources"]["title"]["pdf_page"] == 1


def test_creation_date_is_not_publication_year(tmp_path):
    p = make_paper(tmp_path / "paper.pdf", {"creationDate": "D:20230101000000"},
                   [(80, "Evidence Search for Libraries", 20), (140, "Alice Smith", 12), (240, "No publication date is available.", 10)])
    assert extract_metadata(p)["metadata"]["year"] is None


def test_multiple_author_rows_and_affiliations(tmp_path):
    p = make_paper(tmp_path / "authors.pdf", lines=[(80, "A Title About Retrieval Systems", 20),
        (120, "Alice Smith*, Bob Jones,", 12), (138, "Carol Lee and Dave Chen", 12),
        (160, "Research Institute", 10), (200, "Abstract", 11)])
    assert extract_metadata(p)["metadata"]["authors"] == ["Alice Smith", "Bob Jones", "Carol Lee", "Dave Chen"]


def test_numbered_affiliation_is_not_a_person(tmp_path):
    p = make_paper(tmp_path / "affiliation.pdf", lines=[(80, "A Title About Retrieval Systems", 20),
        (120, "Alice Smith and Bob Jones", 12), (140, "1 Example Group", 12), (200, "Abstract", 11)])
    assert extract_metadata(p)["metadata"]["authors"] == ["Alice Smith", "Bob Jones"]


def test_email_rows_do_not_hide_later_authors(tmp_path):
    p = make_paper(tmp_path / "emails.pdf", lines=[(80, "A Title About Retrieval Systems", 20),
        (120, "Alice Smith", 12), (135, "alice@example.com", 9),
        (150, "Bob Jones", 12), (165, "bob@example.com", 9), (200, "Abstract", 11)])
    assert extract_metadata(p)["metadata"]["authors"] == ["Alice Smith", "Bob Jones"]


def test_scan_has_no_invented_metadata(tmp_path):
    p = tmp_path / "scan.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(p)
    r = extract_metadata(p)
    assert r["metadata"] == dict(title=None, authors=[], year=None, language="unknown", source_url=None)
    assert any("OCR" in w for w in r["warnings"])


def test_multiple_years_left_blank(tmp_path):
    p = make_paper(tmp_path / "p.pdf", lines=[(80, "Paper Title for Testing", 20), (140, "Published: 2022", 10), (170, "Published: 2023", 10)])
    assert extract_metadata(p)["metadata"]["year"] is None


def test_identifiers_not_pdf_creation_date(tmp_path):
    p = make_paper(tmp_path / "p.pdf", lines=[(80, "A Search Paper Title", 20), (140, "arXiv:1908.10084v1", 10)])
    m = extract_metadata(p)["metadata"]
    assert m["source_url"] == "https://arxiv.org/abs/1908.10084" and m["year"] is None


def test_later_reference_dates_and_identifiers_not_used(tmp_path):
    p = tmp_path / "references.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((40, 80), "Title Without Publication Information", fontsize=20)
        pdf.new_page().insert_text((40, 80), "References: Published: 1999 DOI: 10.1234/other-paper")
        pdf.save(p)
    m = extract_metadata(p)["metadata"]
    assert m["year"] is None and m["source_url"] is None


@pytest.mark.parametrize("text,expected", [("Jane Doe, John Smith", ["Jane Doe", "John Smith"]),
    ("Doe, Jane", ["Doe, Jane"]), ("张三，李四", ["张三", "李四"]),
    ("Department of Computer Science", []), ("somebody@example.com", [])])
def test_author_names(text, expected):
    assert author_names(text) == expected


def test_broken_and_encrypted_pdf(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not pdf")
    with pytest.raises(ProjectError):
        extract_metadata(p)
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(tmp_path / "locked.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="private")
    with pytest.raises(ProjectError):
        extract_metadata(tmp_path / "locked.pdf")
