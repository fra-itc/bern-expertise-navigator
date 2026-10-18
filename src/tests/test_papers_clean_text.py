"""NUL bytes and lone surrogates never reach the store (no network, DB or model)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import papers  # noqa: E402
from navigator.schema import Work, clean_text  # noqa: E402


def test_clean_text_drops_nul_and_lone_surrogates_keeps_unicode():
    assert clean_text("a\x00b\ud83dc\udc00d") == "abcd"
    keep = "Müller Bärfuss é ß 北京 😀 \n\t"
    assert clean_text(keep) == keep
    assert clean_text("") == ""


def test_pdf_text_files_with_nul_give_clean_chunks(tmp_path):
    (tmp_path / "abc.txt").write_text("Zürich \x00 study " + " ".join(f"w\x00{i}" for i in range(500)),
                                      encoding="utf-8", newline="\n")
    w = Work(id="W1", title="Ti\x00tle", abstract="Abs\x00tract", pdf_sha1="abc", fetched_at="2026-10-18T00:00:00+00:00")
    chunks = papers.paper_chunks(w, tmp_path)
    assert {k for k, _, _ in chunks} == {"abstract", "fulltext"} and len(chunks) > 2
    assert all("\x00" not in t for _, _, t in chunks)
    assert chunks[0][2] == "Title. Abstract" and "Zürich" in chunks[1][2]
