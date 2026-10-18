"""OpenAlex duplicate work records sharing one DOI: merged into one canonical work (no network, DB or model)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import papers  # noqa: E402
from navigator.papers import CollectResult  # noqa: E402
from navigator.schema import AuthorMatch, EntityLink, PaperAuthor, Work  # noqa: E402

T = "2026-10-18T00:00:00+00:00"


def work(wid, doi=None, authors=(), links=(), refs=(), **kw) -> Work:
    return Work(id=wid, doi=doi, title=f"title {wid}", fetched_at=T,
                authors=[PaperAuthor(position=i, author_id=a, name=a) for i, a in enumerate(authors)],
                links=list(links), referenced_works=list(refs), **kw)


def author_link(eid, aid, pos=None):
    return EntityLink(entity_id=eid, relation="author", author_id=aid, position=pos)


def dup_batch():
    # W7164684003 has more authorships -> canonical although its id is higher
    a = work("W7213651789", "10.1007/s10554-026-03741-6", authors=["A1"], links=[author_link("e1", "A1", 0)],
             refs=["W1"], topics=[{"id": "T1", "display_name": "x"}])
    b = work("W7164684003", "10.1007/S10554-026-03741-6", authors=["A9", "A2", "A1"],
             links=[author_link("e2", "A2", 1)], refs=["W2"], abstract="abs")
    citing = work("W5", "10.1/other", refs=["W7213651789", "W7164684003"])
    lone = work("W6", None, refs=["W7213651789"])
    return [a, b, citing, lone]


def test_dedupe_picks_richer_record_and_remaps_links_and_citations():
    batch = dup_batch()
    before = [w.model_dump() for w in batch]
    out, alias = papers.dedupe_by_doi(batch)
    assert alias == {"W7213651789": "W7164684003"}
    assert set(out) == {"W7164684003", "W5", "W6"}
    keep = out["W7164684003"]
    # both people stay authors; e1's position is re-read from the canonical authorship list (A1 at index 2)
    assert {(l.entity_id, l.author_id, l.position) for l in keep.links} == {("e2", "A2", 1), ("e1", "A1", 2)}
    assert keep.referenced_works == ["W2", "W1"]
    # citations of the dropped id point to the canonical one, no duplicate reference
    assert out["W5"].referenced_works == ["W7164684003"]
    assert out["W6"].referenced_works == ["W7164684003"]
    assert keep.abstract == "abs" and keep.topics == [{"id": "T1", "display_name": "x"}]  # canonical had none
    assert [w.model_dump() for w in batch] == before  # pure


def test_dedupe_tie_breaks_on_lowest_numeric_id_and_is_order_independent():
    a = work("W7212026332", "10.1038/s42003-026-10297-7", authors=["A1"])
    b = work("W7162790536", "10.1038/s42003-026-10297-7", authors=["A2"])
    c = work("W999", "10.1038/s42003-026-10297-7", authors=["A3"])  # fewer digits: numeric, not string order
    for order in ([a, b, c], [c, b, a]):
        out, alias = papers.dedupe_by_doi(order)
        assert list(out) == ["W999"] and alias == {"W7212026332": "W999", "W7162790536": "W999"}


def test_dedupe_prefers_abstract_then_fulltext():
    a = work("W1", "10.1/x", authors=["A1"])
    b = work("W2", "10.1/x", authors=["A1"], abstract="abs")
    assert list(papers.dedupe_by_doi([a, b])[0]) == ["W2"]
    c = work("W3", "10.1/y", authors=["A1"], abstract="a")
    d = work("W4", "10.1/y", authors=["A1"], abstract="a", fulltext_status="ok", pdf_sha1="f" * 40,
             pdf_url="https://x/p.pdf", fulltext_chars=10)
    assert list(papers.dedupe_by_doi([c, d])[0]) == ["W4"]


def test_dedupe_carries_fulltext_and_matched_authorship_entity():
    keep = work("W1", "10.1/x", authors=["A1", "A2"], fulltext_status="not_oa")
    drop = work("W2", "10.1/x", authors=["A2"], is_oa=True, pdf_urls=["https://x/p.pdf"], fulltext_status="ok",
                pdf_url="https://x/p.pdf", pdf_sha1="a" * 40, fulltext_chars=42)
    drop.authors[0].entity_id = "e2"
    out, _ = papers.dedupe_by_doi([keep, drop])
    w = out["W1"]
    assert (w.fulltext_status, w.pdf_sha1, w.fulltext_chars, w.is_oa) == ("ok", "a" * 40, 42, True)
    assert w.authors[1].entity_id == "e2"


def test_dedupe_without_duplicates_is_identity():
    ws = [work("W1", "10.1/a"), work("W2", None), work("W3", None)]
    out, alias = papers.dedupe_by_doi(ws)
    assert alias == {} and list(out) == ["W1", "W2", "W3"]


def test_merge_results_dedupes_previous_jsonl_and_reports_count():
    """The server's JSONL held both records of a DOI: the resumed run writes one work per DOI."""
    prev = dup_batch()[:2]
    res = CollectResult(works={"W5": work("W5", "10.1/other", refs=["W7213651789"])},
                        matches=[AuthorMatch(entity_id="e1", entity_name="E", candidates=[], chosen_author_id="A1",
                                             decided_by="known_id", reason="")], stats={"works": 1})
    merged = papers.merge_results(prev, [], res)
    assert set(merged.works) == {"W7164684003", "W5"}
    assert merged.stats["total_works_duplicate_doi_merged"] == 1
    assert merged.works["W5"].referenced_works == ["W7164684003"]
    assert {l.entity_id for l in merged.works["W7164684003"].links} == {"e1", "e2"}


def test_write_to_store_dedupes_before_the_store(tmp_path):
    seen = {}

    class Store:
        supports_papers = True

        def write_papers(self, works, matches, chunks):
            seen["ids"], seen["chunks"] = sorted(w.id for w in works), sorted(chunks)
            return {"papers": len(works)}

    out = papers.write_to_store(Store(), dup_batch(), [], text_dir=tmp_path)
    assert out == {"duplicate_doi_merged": 1, "papers": 3}
    assert seen["ids"] == seen["chunks"] == ["W5", "W6", "W7164684003"]
