import json

import numpy as np
import pytest

from ehr2summary.cli import main
from ehr2summary.faithfulness import FaithfulnessChecker
from ehr2summary.generators import HallucinationInjector, OmissionInjector, TemplateGenerator
from ehr2summary.metrics import bootstrap_ci, kendall_tau_b, rankdata, rouge_l, rouge_n, spearman
from ehr2summary.pipeline import agreement, read_ratings, run_benchmark, summarize
from ehr2summary.records import lexicon
from ehr2summary.summary import Statement


def test_template_summary_is_faithful(records, checker):
    for rec in records:
        rep = checker.check(rec, TemplateGenerator().generate(rec))
        assert rep.precision == 1.0 and not rep.hallucinated


def test_injected_hallucinations_are_found(records, tables, checker):
    gen = HallucinationInjector(TemplateGenerator(), lexicon(tables), n=2)
    for rec in records:
        rep = checker.check(rec, gen.generate(rec))
        assert rep.hallucinated and len(rep.unsupported_terms) == 2 and rep.precision < 1.0


def test_invalid_refs_and_unknown_codes(records, checker):
    rec = records[0]
    s = TemplateGenerator().generate(rec)
    s.sections["diagnoses"].append(Statement(text="See ICD-9 code 999.9 for details.", refs=["dx99"]))
    rep = checker.check(rec, s)
    assert rep.invalid_refs == ["dx99"] and rep.unknown_codes == ["999.9"]


def test_longest_term_wins():
    c = FaithfulnessChecker({"diagnosis": {"Heart failure", "Acute on chronic heart failure"}})
    assert c.find_terms("Acute on chronic heart failure was treated.") == ["acute on chronic heart failure"]


def test_summary_for_another_record_is_refused(records, checker):
    s = TemplateGenerator().generate(records[0])
    with pytest.raises(ValueError):
        checker.check(records[1], s)


def test_omission_lowers_recall(records, checker):
    rec = next(r for r in records if len(r.diagnoses) > 2)
    assert checker.check(rec, OmissionInjector(TemplateGenerator()).generate(rec)).recall < 1.0


def test_rouge_values():
    assert rouge_n("the cat sat", "the cat sat", 1) == 1.0
    assert rouge_n("the cat", "the dog", 1) == pytest.approx(0.5)
    assert rouge_n("a b c d", "a b x d", 2) == pytest.approx(1 / 3)
    assert rouge_l("a b c d", "a x c d") == pytest.approx(0.75)
    assert rouge_l("", "a") == 0.0


def test_rank_correlations():
    assert list(rankdata([10, 20, 20, 30])) == [1, 2.5, 2.5, 4]
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert kendall_tau_b([1, 2, 3], [1, 3, 2]) == pytest.approx(1 / 3)
    assert np.isnan(spearman([1, 1, 1], [1, 2, 3]))


def test_bootstrap_ci_contains_mean():
    mean, lo, hi = bootstrap_ci([1, 2, 3, 4, 5], seed=1)
    assert lo <= mean <= hi and mean == 3


def test_benchmark_summary_ranks_systems(records, tables, checker):
    gens = [TemplateGenerator(), HallucinationInjector(TemplateGenerator(), lexicon(tables)),
            OmissionInjector(TemplateGenerator())]
    from ehr2summary.judge import RuleJudge

    report = summarize(run_benchmark(records, gens, checker, RuleJudge(checker)))
    s = report["systems"]
    assert s["template"]["hallucination_rate"]["mean"] == 0.0
    assert s["template+hallucination"]["hallucination_rate"]["mean"] == 1.0
    assert s["template+omission"]["entity_recall"]["mean"] < s["template"]["entity_recall"]["mean"]
    assert "rougeL" in s["template"]


def test_ratings_and_agreement(tmp_path):
    rows = [{"record_id": f"r{i}", "system": "s", "judge": {"scores": {"clinical_accuracy": float(i),
             "completeness": 5.0, "readability": 5.0, "actionability": 5.0}}} for i in range(5)]
    lines = ["record_id,system,criterion,rating"]
    lines += [f"r{i},s,clinical_accuracy,{i * 2}" for i in range(5)] + ["r0,s,clinical_accuracy,2"]
    (tmp_path / "h.csv").write_text("\n".join(lines) + "\n")
    ratings = read_ratings(tmp_path / "h.csv")
    assert ratings[("r0", "s", "clinical_accuracy")] == 1.0
    out = agreement(rows, ratings)
    assert out["clinical_accuracy"]["spearman"] == pytest.approx(1.0) and out["completeness"]["n"] == 0
    (tmp_path / "bad.csv").write_text("record_id,system,criterion,rating\nr0,s,clinical_accuracy,12\n")
    with pytest.raises(ValueError):
        read_ratings(tmp_path / "bad.csv")


def test_cli_demo_and_commands(tmp_path, capsys):
    assert main(["demo", "--out", str(tmp_path / "demo")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["records"] == 40 and report["synthetic"] is True
    assert (tmp_path / "demo" / "rows.jsonl").exists()
    data = tmp_path / "demo" / "data"
    assert main(["records", "--data-dir", str(data), "--n", "5", "--out", str(tmp_path / "r.jsonl")]) == 0
    capsys.readouterr()
    assert main(["run", "--data-dir", str(data), "--records", str(tmp_path / "r.jsonl"), "--systems",
                 "template,omission", "--judge", "none", "--out", str(tmp_path / "run")]) == 0
    assert json.loads(capsys.readouterr().out)["records"] == 5
    assert main(["run", "--data-dir", str(data), "--systems", "nonsense"]) == 2
    assert main(["run", "--data-dir", str(tmp_path / "missing")]) == 2


def test_generation_failure_is_recorded_not_fatal(records, checker):
    from ehr2summary.generators import LLMGenerator
    from ehr2summary.llm import ScriptedChatModel

    gen = LLMGenerator(ScriptedChatModel(["bad", "bad"]), max_attempts=2)
    result = run_benchmark(records[:1], [gen], checker)
    assert result.rows == [] and result.failures[0]["record_id"] == records[0].record_id
