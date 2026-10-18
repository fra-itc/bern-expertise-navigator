"""tools/replay_topics.py: recorded topic decisions replayed with the current parsing, no LLM, no DB."""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import replay_topics  # noqa: E402
from navigator import llm  # noqa: E402

COLS = ["openalex_topic_id", "openalex_label", "topic_key", "topic_label", "is_new", "decided_by", "reason",
        "candidates", "decided_at"]


def _write(tmp_path, rows, graph):
    tm, gt = tmp_path / "topic_map.csv", tmp_path / "graph_topics.csv"
    with tm.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        w.writerows(rows)
    with gt.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "label"])
        w.writerows([[json.dumps(k), json.dumps(l)] for k, l in graph.items()])
    return tm, gt


def test_replay_recovers_answers_and_counts(tmp_path, capsys):
    cands = json.dumps(["audiology", "hearing loss and rehabilitation"])
    rows = [
        # the pilot bug: the label of the identical Topic was answered -> now identity rule (no LLM)
        ["T1", "Audiology", "audiology", "Audiology", "t", "llm",
         "invalid choice 'Audiology' discarded, new topic (Exact match.)", cands, ""],
        # the label of another candidate -> now a valid reuse
        ["T2", "Hearing Impairment", "hearing impairment", "Hearing Impairment", "t", "llm",
         "invalid choice \"Hearing Loss and Rehabilitation\" discarded, new topic (close)", cands, ""],
        # the LLM said new -> still new (and the Topic it created is not part of the vocabulary before the run)
        ["T3", "Tinnitus", "tinnitus", "Tinnitus", "t", "llm", "No candidate matches", cands, ""],
        ["T4", "Hearing Loss", "hearing loss and rehabilitation", "Hearing Loss and Rehabilitation", "f", "llm",
         "same", cands, ""],
    ]
    graph = {"audiology": "Audiology", "hearing loss and rehabilitation": "Hearing Loss and Rehabilitation",
             "tinnitus": "Tinnitus"}
    tm, gt = _write(tmp_path, rows, graph)
    real = llm.chat_json
    assert replay_topics.main(["--topic-map", str(tm), "--graph-topics", str(gt)]) == 0
    assert llm.chat_json is real  # the recorded-answer stand-in is removed again
    out = json.loads(capsys.readouterr().out)
    assert out["vocabulary_before_run"] == 2 and out["before"] == {"invalid": 2, "new_other": 1, "reused": 1}
    inv = out["by_original_category"]["invalid"]
    assert (inv["reuse_identical_key"], inv["reuse_other_candidate"], inv["new"]) == (1, 1, 0)
    assert out["after"] == {"reuse": 3, "new": 1} and out["llm_calls_needed"] == 3
    # a shortlist of 1 makes the second candidate unreachable: the recorded answer becomes invalid -> new
    assert replay_topics.main(["--topic-map", str(tm), "--graph-topics", str(gt), "--shortlist", "1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["after"] == {"reuse": 1, "new": 3} and out["by_original_category"]["invalid"]["still_invalid"] == 1
