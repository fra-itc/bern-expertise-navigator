"""Query expansion (R2: lay terms -> the experts' vocabulary) with Apertus stubbed: prompt, grounding, merge."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import config, llm, search  # noqa: E402
from test_search_offline import built  # noqa: E402,F401  (built: the shared fixture)


@pytest.fixture(autouse=True)
def _fresh_cache():
    search.llm_analyze.cache_clear()
    yield
    search.llm_analyze.cache_clear()


class FakeLLM:
    """Stands in for llm.chat_json: records the prompts, answers with a fixed expansion (or raises)."""

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.prompts = answer or {}, error, []

    def __call__(self, messages, schema, **kw):
        self.prompts.append(messages[-1]["content"])
        if self.error:
            raise self.error
        return schema(**self.answer)


@pytest.fixture()
def llm_on(built, monkeypatch):
    monkeypatch.setattr(config.settings, "use_llm_expansion", True)
    monkeypatch.setattr(search.llm, "available", lambda: True)

    def use(fake, ground=False):
        monkeypatch.setattr(config.settings, "ground_expansion", ground)
        monkeypatch.setattr(search.llm, "chat_json", fake)
        return fake
    return use


def test_merge_orders_restatement_grounded_expert_then_translations():
    r = search._Expansion(technical_query="Cochlear implant surgery",
                          index_terms=["Hearing Research Lab", "otology"],          # 'otology' is not in the list
                          expert_terms=["cochlear implantation", "otosurgery", "ci", "extra"],
                          translations=["Cochlea-Implantat", "implant cochléaire", "third"])
    a = search.merge_expansion(r, ["Hearing Research Lab", "Big Lab"], q="hearing aids")
    assert a.terms == ["cochlear implant surgery", "hearing research lab", "otology", "cochlear implantation",
                       "otosurgery", "cochlea-implantat", "implant cochléaire"]
    assert a.grounded == ["hearing research lab"]      # an invented 'index term' is not grounded
    assert a.rewrite == "cochlear implant surgery"


def test_merge_caps_each_bucket_and_the_total():
    r = search._Expansion(technical_query="t", index_terms=[f"c{i}" for i in range(9)],
                          expert_terms=[f"e{i}" for i in range(9)], translations=[f"x{i}" for i in range(9)])
    a = search.merge_expansion(r, [f"c{i}" for i in range(9)])
    assert a.grounded == ["c0", "c1", "c2"]
    assert len(a.terms) <= search.MAX_LLM_TERMS
    assert sum(t.startswith("x") for t in a.terms) <= search.MAX_TRANSLATIONS
    assert sum(t.startswith("e") for t in a.terms) <= search.MAX_EXPERT_TERMS


def test_merge_drops_the_query_itself():
    a = search.merge_expansion(search._Expansion(technical_query="Glucose Sensors", expert_terms=["cgm"]),
                               [], q="glucose sensors")
    assert a.terms == ["cgm"] and a.rewrite == ""


def test_vocabulary_candidates_come_from_the_index(built):
    c = search.vocabulary_candidates("cochlear implant")
    assert "cochlear implant" not in [x.lower() for x in c]          # the query itself is not a candidate
    labels = {x.lower() for e in built for x in [*e.expertise, *e.infrastructure, e.unit or "", e.name]}
    assert c and all(x.lower() in labels for x in c)
    assert "Hearing Research Lab" in c
    assert "Max Muster" not in c                                     # people's names are never vocabulary


def test_prompt_asks_for_technical_terms_before_translations(llm_on):
    fake = llm_on(FakeLLM({"technical_query": "continuous glucose monitoring"}))
    search.analyze_query("sugar level patch")
    p = fake.prompts[0]
    assert p.index("technical_query") < p.index("expert_terms") < p.index("translations")
    assert "INDEX TERMS:\n- (none)" in p                             # grounding off by default


def test_grounded_prompt_lists_index_vocabulary(llm_on):
    fake = llm_on(FakeLLM({"index_terms": ["Hearing Research Lab"]}), ground=True)
    a = search.analyze_query("ear operations")
    assert "- Hearing Research Lab" in fake.prompts[0]
    assert a.grounded == ["hearing research lab"]


def test_glossary_terms_rank_ahead_of_llm_terms(llm_on):
    llm_on(FakeLLM({"technical_query": "glucose biosensing", "expert_terms": ["wearable sensing"]}))
    terms = search.analyze_query("glucose sensors").terms
    gl = [t for t in search.glossary_terms("glucose sensors") if t != "glucose sensors"]
    assert gl and terms[:len(gl)] == gl
    assert terms.index("glucose biosensing") >= len(gl)


def test_llm_failure_falls_back_to_glossary_and_reports_the_error(llm_on, caplog):
    llm_on(FakeLLM(error=llm.LLMError("HTTP 504: gateway timeout")))
    with caplog.at_level("WARNING", logger="navigator.search"):
        a = search.analyze_query("glucose sensors")
        r = search.search("glucose sensors")
    assert a.error == "LLMError: HTTP 504: gateway timeout"
    assert a.terms == [t for t in search.glossary_terms("glucose sensors") if t != "glucose sensors"]
    assert "query expansion failed" in caplog.text
    assert not r.abstained and "Jane Doe" in [x.person_or_unit for x in r.results]


def test_grounded_terms_cannot_prevent_abstention(llm_on):
    # the model picks a label from the very candidates the abstention check looks at: no free pass
    llm_on(FakeLLM({"index_terms": ["medical image analysis"]}), ground=True)
    r = search.search("volcano geochemistry iceland")
    assert r.abstained and not r.results


def test_restatement_is_searched_semantically_first(llm_on, monkeypatch):
    llm_on(FakeLLM({"technical_query": "cochlear implant", "expert_terms": ["otology"]}))
    seen = {}
    real = search.vector_rank

    def spy(q, extra, **kw):
        seen["extra"] = list(extra)
        return real(q, extra, **kw)
    monkeypatch.setattr(search, "vector_rank", spy)
    r = search.search("ear operations")
    assert seen["extra"][0] == "cochlear implant"
    assert "Max Muster" in [x.person_or_unit for x in r.results]
