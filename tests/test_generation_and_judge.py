import json

import httpx
import pytest

from ehr2summary.config import ModelSettings
from ehr2summary.generators import HallucinationInjector, LLMGenerator, OmissionInjector, TemplateGenerator
from ehr2summary.judge import JudgeIndependenceError, LLMJudge, RuleJudge, ensure_independent, parse_scores
from ehr2summary.llm import (
    LLMError,
    OpenAICompatibleChatModel,
    PrivacyError,
    ScriptedChatModel,
    score_distribution_from_top_logprobs,
)
from ehr2summary.prompts import GENERATOR_SYSTEM, RUBRIC, generator_messages, judge_messages
from ehr2summary.records import lexicon
from ehr2summary.summary import SummaryFormatError, parse_summary

SCORES = json.dumps({c: {"score": 8, "reason": "ok"} for c in RUBRIC})


def test_generator_prompt_has_no_rubric_and_forbids_invention(records):
    msgs = generator_messages(records[0])
    assert "Clinical" not in GENERATOR_SYSTEM and "score" not in GENERATOR_SYSTEM.lower()
    assert "Not documented in the record" in GENERATOR_SYSTEM
    assert records[0].diagnoses[0].text in msgs[1]["content"]


def test_judge_prompt_contains_the_source_record(records):
    rec = records[0]
    summary = TemplateGenerator().generate(rec)
    content = judge_messages(rec, summary)[1]["content"]
    assert "Source record" in content and rec.diagnoses[0].text in content and "Summary to evaluate" in content


def test_llm_generator_uses_record_id_not_reply_id(records):
    rec = records[0]
    reply = json.dumps({"record_id": "r-000000000000", "sections": {"diagnoses": [{"text": "x", "refs": ["dx1"]}]}})
    model = ScriptedChatModel(["not json", reply])
    s = LLMGenerator(model, seed=3).generate(rec)
    assert s.record_id == rec.record_id and s.sections["procedures"] == []
    assert model.calls[0]["temperature"] == 0.0 and model.calls[0]["seed"] == 3


def test_parse_summary_rejects_unknown_sections():
    with pytest.raises(SummaryFormatError):
        parse_summary('{"sections": {"chief_complaint": []}}', "r-0", "x")
    s = parse_summary('```json\n{"follow_up": "Home."}\n```', "r-0", "x")
    assert s.sections["follow_up"][0].text == "Home."


def test_real_records_do_not_go_to_remote_endpoints(records):
    real = records[0].model_copy(update={"synthetic": False})
    remote = ScriptedChatModel([], identity="openai:gpt", is_local=False)
    with pytest.raises(PrivacyError):
        LLMGenerator(remote).generate(real)
    with pytest.raises(PrivacyError):
        LLMJudge(remote).score(real, TemplateGenerator().generate(real))
    local = ScriptedChatModel(['{"sections": {}}'], is_local=True)
    assert LLMGenerator(local).generate(real).record_id == real.record_id


def test_judge_must_differ_from_generator():
    with pytest.raises(JudgeIndependenceError):
        ensure_independent("llm:openai:mistral", "openai:mistral", allow_self=False)
    ensure_independent("llm:openai:mistral", "openai:llama3", allow_self=False)
    ensure_independent("llm:openai:mistral", "openai:mistral", allow_self=True)


def test_parse_scores_variants():
    assert parse_scores(SCORES)[0]["completeness"] == 8.0
    alt = json.dumps({"Clinical Accuracy": "7/10", "Completeness": 6, "Readability": {"score": 9}, "Actionability": 5})
    assert parse_scores(alt)[0] == {"clinical_accuracy": 7.0, "completeness": 6.0, "readability": 9.0,
                                    "actionability": 5.0}
    with pytest.raises(SummaryFormatError):
        parse_scores(json.dumps({c: 11 for c in RUBRIC}))
    with pytest.raises(SummaryFormatError):
        parse_scores('{"clinical_accuracy": 5}')


def test_llm_judge_averages_samples(records):
    rec = records[0]
    other = json.dumps({c: {"score": 6, "reason": "r"} for c in RUBRIC})
    model = ScriptedChatModel([SCORES, "garbage", other])
    res = LLMJudge(model, samples=2, temperature=0.7, seed=10).score(rec, TemplateGenerator().generate(rec))
    assert res.scores["readability"] == 7.0 and res.spread["readability"] == 1.0 and res.samples == 2
    assert [c["seed"] for c in model.calls] == [10, 11, 11]


def test_logprob_weighted_scores(records):
    top = [{"token": "8", "logprob": -0.2231}, {"token": "7", "logprob": -1.6094}, {"token": "x", "logprob": -3}]
    dist = score_distribution_from_top_logprobs(top)
    assert dist[8] == pytest.approx(0.8, abs=1e-3) and dist[7] == pytest.approx(0.2, abs=1e-3)

    def handler(request):
        body = json.loads(request.content)
        assert body["logprobs"] is True and body["max_tokens"] == 2
        return httpx.Response(200, json={"choices": [{"message": {"content": "8"},
                                                      "logprobs": {"content": [{"top_logprobs": top}]}}]})

    model = OpenAICompatibleChatModel(ModelSettings("openai", "judge-m"), transport=httpx.MockTransport(handler))
    rec = records[0]
    res = LLMJudge(model, mode="logprob").score(rec, TemplateGenerator().generate(rec))
    assert res.scores["completeness"] == pytest.approx(7.8, abs=0.01)


def test_openai_adapter_errors_and_json_mode():
    seen = {}

    def ok(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    m = OpenAICompatibleChatModel(ModelSettings("openai", "m"), transport=httpx.MockTransport(ok))
    assert m.complete([{"role": "user", "content": "x"}], json_mode=True, seed=4) == "{}"
    assert seen["response_format"] == {"type": "json_object"} and seen["seed"] == 4
    bad = OpenAICompatibleChatModel(ModelSettings("openai", "m"), transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(LLMError):
        bad.complete([{"role": "user", "content": "x"}])
    with pytest.raises(LLMError):
        OpenAICompatibleChatModel(ModelSettings("openai", ""))
    assert OpenAICompatibleChatModel(ModelSettings("openai", "m", base_url="https://api.example.com/v1")).is_local is False


def test_rule_judge_and_injectors(records, tables, checker):
    rec = next(r for r in records if r.medications and len(r.diagnoses) > 2)
    judge = RuleJudge(checker)
    good = judge.score(rec, TemplateGenerator().generate(rec)).scores
    bad = judge.score(rec, HallucinationInjector(TemplateGenerator(), lexicon(tables), n=2).generate(rec)).scores
    short = judge.score(rec, OmissionInjector(TemplateGenerator()).generate(rec)).scores
    assert good["clinical_accuracy"] == 10 and bad["clinical_accuracy"] < good["clinical_accuracy"]
    assert short["completeness"] < good["completeness"]
