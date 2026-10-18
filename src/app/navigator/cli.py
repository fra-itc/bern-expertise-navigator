"""Pipeline CLI:  python -m navigator.cli {crawl,extract,index,all,stats} [--source NAME]  |  papers {collect,embed,link,topics,all}"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import classify, crawl, extract, index, llm, openalex
from .config import DATA_DIR, load_sources, settings
from .schema import Entity, Page


def cmd_crawl(a):
    if not a.source:
        # Crawling hits other people's servers: only ever one explicitly named source at a time.
        raise SystemExit("[crawl] name the source to fetch: crawl --source <name>  (make crawl SOURCE=<name>)")
    for s in load_sources(a.source):
        saved = DATA_DIR / "pages" / f"{s.name}.jsonl"
        if saved.exists() and saved.stat().st_size and not a.recrawl:
            # Be polite: never hit a site again by accident. Re-crawling is an explicit decision.
            print(f"[crawl] {s.name}: using saved pages ({saved}); pass --recrawl (make crawl RECRAWL=1) to fetch again")
            continue
        openalex.fetch(s) if s.type == "openalex" else crawl.crawl(s)


def _process(p: Page, src, use_llm_classify: bool, extractor: str) -> tuple[Page, list, list[dict], str | None]:
    rejected: list[dict] = []
    if src and src.type == "openalex":
        # structured scholarly record: no classification or AI needed, same snippet verifier as the websites
        ext, pubs = openalex.to_extracted(p)
        v = extract.verify(ext, p, rejected)
        if not v:
            return p, [], rejected, None
        ent = extract.to_entity(v, p, src.label, "openalex")
        ent.evidence += openalex.publication_evidence(p, pubs)
        return p, [ent], rejected, None
    p.page_type = classify.classify(p, src, use_llm=use_llm_classify)
    if p.page_type == "other" and extractor == "apertus":
        return p, [], rejected, None
    try:
        ents = [extract.to_entity(e, p, src.label if src else p.source, extractor)
                for e in extract.extract_page(p, rejected, extractor)]
        return p, ents, rejected, None
    except Exception as ex:  # keep the batch going
        return p, [], rejected, f"{type(ex).__name__}: {ex}"


def _choose_extractor(requested: str) -> str:
    if requested == "rules":
        return "rules"
    try:
        print(f"[extract] Apertus: {llm.ping()} at {settings.llm_base_url}")
        return "apertus"
    except llm.LLMError as e:
        if requested == "apertus":
            raise SystemExit(f"[extract] {e}")
        print(f"[extract] {e}\n[extract] -> falling back to the deterministic rules extractor (no LLM)")
        return "rules"


def cmd_extract(a):
    extractor = _choose_extractor(a.extractor)
    use_llm_classify = extractor == "apertus" and not a.no_llm_classify
    srcs = {s.name: s for s in load_sources()}
    pages = crawl.load_pages(a.source)
    if a.limit:
        pages = pages[: a.limit]
    out_path = DATA_DIR / "extracted.jsonl"
    # Re-processing one source keeps the entities already extracted for the others
    existing: list[Entity] = []
    if a.source and out_path.exists():
        existing = [Entity.model_validate_json(l) for l in out_path.open()
                    if l.strip() and json.loads(l)["source"] != a.source]
    rejected: list[dict] = []
    ents: list[Entity] = []
    types: Counter[str] = Counter()
    errors = 0
    llm.reset_usage()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=settings.llm_concurrency) as pool:
        futs = [pool.submit(_process, p, srcs.get(p.source), use_llm_classify, extractor) for p in pages]
        for i, f in enumerate(as_completed(futs), 1):
            p, es, rj, err = f.result()
            types[p.page_type or "other"] += 1
            ents += es
            rejected += rj
            if err:
                errors += 1
                print(f"  ! {p.url}: {err[:200]}")
            if i % 25 == 0:
                print(f"[extract] {i}/{len(pages)} pages, {len(ents)} entities, {len(rejected)} rejected claims")
    merged = extract.link_site_structure(extract.merge(existing + ents))
    merged = openalex.attach_to_web_profiles(merged, {s.name for s in srcs.values() if s.type == "openalex"})
    merged = extract.derive_units(merged)
    crawl.dump_jsonl(merged, out_path)
    extract.write_rejected(rejected, a.source)
    n_llm_pages = sum(v for k, v in types.items() if k != "other")
    stats = {
        "extractor": extractor, "pages": len(pages), "page_types": dict(types), "pages_sent_to_llm": n_llm_pages, "errors": errors,
        "entities": len(merged), "claims_rejected": len(rejected), "seconds": round(time.time() - t0, 1),
        "llm_usage": dict(llm.usage),
        "tokens_per_llm_page": round((llm.usage["prompt_tokens"] + llm.usage["completion_tokens"])
                                     / max(1, llm.usage["calls"]), 1),
    }
    (DATA_DIR / f"extract_stats{'_' + a.source if a.source else ''}.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))
    print(f"[extract] {len(merged)} entities -> {out_path}; {len(rejected)} unsupported claims dropped")


def cmd_index(a):
    p = DATA_DIR / "extracted.jsonl"
    ents = [Entity.model_validate_json(l) for l in p.open() if l.strip()]
    # --source: the Postgres backend replaces only that source (one transaction); files always rebuild all
    index.build(ents, sources=[a.source] if a.source else None)


def cmd_all(a):
    """extract + index from the saved pages; crawling is never implied."""
    cmd_extract(a); cmd_index(a)


def cmd_stats(a):
    pages = crawl.load_pages()
    ents = index.load_entities().values()
    print(json.dumps({
        "pages_per_source": Counter(p.source for p in pages),
        "entities_per_source": Counter(e.source for e in ents),
        "entities_per_type": Counter(e.entity_type for e in ents),
    }, indent=2))


def cmd_papers(a):
    """papers {collect,embed,link,topics,all}: OpenAlex papers of the indexed people (see navigator/papers.py).
    topics = only the topic mapping and the ABOUT edges (--remap: decide every topic again on a populated DB)."""
    from . import papers
    from .openalex_client import OpenAlexClient
    from .storage import index_store
    st = index_store()
    # resume: people decided by an earlier run are skipped, its works and PDF outcomes are kept (--redo: all again)
    prev_works, prev_matches = ([], []) if a.redo else papers.load_jsonl()
    skip = papers.decided_ids(prev_matches)
    types = tuple(t.strip() for t in a.types.split(",") if t.strip())
    if a.step == "stats" or a.dry_run:
        est = papers.estimate(list(st.load_entities().values()), crawl.load_pages(), types=types,
                              limit=a.limit_people, skip_ids=skip, previous_works={w.id: w for w in prev_works},
                              use_llm=not a.no_llm, pdf=not a.no_pdf, max_pdfs=a.max_pdfs,
                              people_filter=a.people)
        est = {"backend": st.name, "dry_run": True, "previous": {"works": len(prev_works), "matches": len(prev_matches)},
               **est}
        print(json.dumps(est, indent=2, default=str))
        return
    steps = ["collect", "embed", "link"] if a.step == "all" else [a.step]
    out: dict = {"backend": st.name}
    if "collect" in steps:
        use_llm = False if a.no_llm else llm.available()
        print(f"[papers] matcher: {'LLM ' + settings.llm_model if use_llm else 'rules (no LLM)'}; "
              f"OpenAlex key: {'set' if settings.openalex_api_key else 'not set'}; "
              f"mailto: {'set' if settings.openalex_mailto else 'not set'}; "
              f"resume: {len(skip)} people already decided, {len(prev_works)} works kept")
        ents = list(st.load_entities().values())
        ua = (load_sources() or [None])[0]
        fetcher = None if a.no_pdf else papers.PdfFetcher(user_agent=ua.user_agent if ua else None)
        client = OpenAlexClient()
        try:
            res = papers.collect(ents, crawl.load_pages(), client, fetcher=fetcher, use_llm=use_llm,
                                 types=types, limit=a.limit_people, max_pdfs=a.max_pdfs, workers=a.workers,
                                 skip_ids=skip, previous_works={w.id: w for w in prev_works},
                                 previous_matches=prev_matches, people_filter=a.people)
        finally:
            client.close()
        merged = papers.merge_results(prev_works, prev_matches, res)
        papers.save_jsonl(merged)
        out["collect"] = {**res.stats, "total_works": len(merged.works), "total_matches": len(merged.matches)}
        if getattr(st, "supports_papers", False):
            # all works (upserts: unchanged rows and embeddings stay), only this run's decisions in the audit
            out["store"] = papers.write_to_store(st, list(merged.works.values()), res.matches)
        else:
            out["store"] = f"{st.name}: JSONL only ({papers.WORKS_PATH}); embed/link need DATABASE_URL"
    if "embed" in steps:
        out["embed"] = papers.embed_pending(st)
    if "link" in steps:
        out["similar"] = papers.link_similar(st)
    if "link" in steps or "topics" in steps:
        out["topics"] = papers.link_topics(st, use_llm=False if a.no_llm else None, remap=a.remap)
    out["llm_usage"] = dict(llm.usage)
    (DATA_DIR / "papers").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "papers" / f"stats_{a.step}.json").write_text(json.dumps(out, indent=2, default=str),
                                                              encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser(prog="navigator")
    sub = ap.add_subparsers(required=True)
    pp = sub.add_parser("papers", help="OpenAlex papers: collect -> embed -> link (embed/link: Postgres only)")
    pp.add_argument("step", nargs="?", default="all", choices=["collect", "embed", "link", "topics", "all", "stats"],
                    help="stats = estimate only (same as --dry-run)")
    pp.add_argument("--limit-people", "--limit", dest="limit_people", type=int, default=0,
                    help="collect: at most N people not decided yet (incremental runs; 0 = all)")
    pp.add_argument("--people", choices=["all", "known", "search"], default="all",
                    help="collect/stats: all people, only those with a known OpenAlex author id (known), or only "
                         "those that need an author search (search); applied before --limit-people")
    pp.add_argument("--dry-run", action="store_true",
                    help="estimate OpenAlex requests, LLM calls, PDFs and chunks; no network, nothing written")
    pp.add_argument("--redo", action="store_true",
                    help="collect: ignore data/papers/*.jsonl and decide every selected person again")
    pp.add_argument("--types", default="person", help="collect: entity types searched on OpenAlex (person[,unit])")
    pp.add_argument("--max-pdfs", type=int, default=0, help="collect: max OA PDFs to download this run (0 = all)")
    pp.add_argument("--no-pdf", action="store_true", help="collect: metadata and abstracts only")
    pp.add_argument("--no-llm", action="store_true", help="author/topic matching with the deterministic rules only")
    pp.add_argument("--remap", action="store_true",
                    help="link/topics: decide every OpenAlex topic again against the entities' Topic vocabulary and "
                         "rewrite topic_map + ABOUT (no collect, no embed; idempotent)")
    pp.add_argument("--workers", type=int, default=4, help="collect: people processed in parallel")
    pp.set_defaults(fn=cmd_papers)
    for name, fn in [("crawl", cmd_crawl), ("extract", cmd_extract), ("index", cmd_index),
                     ("all", cmd_all), ("stats", cmd_stats)]:
        sp = sub.add_parser(name)
        sp.add_argument("--source", default=None, help="only this source from sources.yaml")
        sp.add_argument("--limit", type=int, default=0, help="extract: max pages (for quick tests)")
        sp.add_argument("--no-llm-classify", action="store_true")
        sp.add_argument("--recrawl", action="store_true",
                        help="crawl: fetch again even if pages are saved (the saved file is replaced only on completion)")
        sp.add_argument("--extractor", choices=["auto", "apertus", "rules"], default="auto",
                        help="extract: auto = Apertus if the endpoint answers, else rules")
        sp.set_defaults(fn=fn)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
