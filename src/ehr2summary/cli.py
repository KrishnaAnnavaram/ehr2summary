"""The ``ehr2summary`` command."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

from .config import ConfigError, Settings
from .faithfulness import FaithfulnessChecker
from .generators import HallucinationInjector, LLMGenerator, OmissionInjector, TemplateGenerator
from .judge import JudgeIndependenceError, LLMJudge, RuleJudge, ensure_independent
from .llm import LLMError, PrivacyError, build_chat_model
from .pipeline import agreement, read_ratings, run_benchmark, summarize, write_outputs
from .records import build_records, lexicon, read_records, select_admissions, write_jsonl
from .synthetic import write_synthetic
from .tables import TableError, load_tables


def _settings(args) -> Settings:
    s = Settings.from_env()
    if getattr(args, "data_dir", None):
        s = replace(s, data_dir=Path(args.data_dir))
    if getattr(args, "out", None) and getattr(args, "command", "") in {"run", "demo"}:
        s = replace(s, work_dir=Path(args.out))
    return s


def _is_synthetic(folder: Path) -> bool:
    return (Path(folder) / "SYNTHETIC").exists()


def cmd_synth(args) -> int:
    out = write_synthetic(Path(args.out), n_admissions=args.n, seed=args.seed)
    print(f"wrote synthetic MIMIC-III style tables to {out}")
    return 0


def cmd_records(args) -> int:
    s = _settings(args)
    tables = load_tables(s.data_dir)
    ids = select_admissions(tables, args.n or s.n_records, s.seed)
    recs = build_records(tables, ids, salt=s.id_salt, synthetic=_is_synthetic(s.data_dir),
                         max_items=s.max_items_per_section, max_labs=s.max_labs)
    write_jsonl(Path(args.out), recs)
    print(f"wrote {len(recs)} records to {args.out}")
    return 0


def _systems(args, s: Settings, lex: dict) -> list:
    systems = []
    for name in args.systems.split(","):
        name = name.strip()
        if name == "template":
            systems.append(TemplateGenerator())
        elif name == "hallucination":
            systems.append(HallucinationInjector(TemplateGenerator(), lex, seed=s.seed))
        elif name == "omission":
            systems.append(OmissionInjector(TemplateGenerator()))
        elif name == "llm":
            systems.append(LLMGenerator(build_chat_model(s.generator), seed=s.seed,
                                        allow_remote=s.allow_remote_records))
        else:
            raise ValueError(f"unknown system {name!r}: use template, hallucination, omission or llm")
    return systems


def _judge(args, s: Settings, checker: FaithfulnessChecker, systems: list):
    if args.judge == "none":
        return None
    if args.judge == "rule":
        return RuleJudge(checker)
    model = build_chat_model(s.judge)
    for g in systems:
        if g.name.startswith("llm:"):
            ensure_independent(g.name, model.identity, s.allow_self_judge)
    return LLMJudge(model, samples=s.judge_samples, temperature=s.judge_temperature, seed=s.seed,
                    mode="logprob" if args.judge == "llm-logprob" else "json", allow_remote=s.allow_remote_records)


def cmd_run(args) -> int:
    s = _settings(args)
    tables = load_tables(s.data_dir)
    if args.records:
        recs = read_records(Path(args.records))
    else:
        ids = select_admissions(tables, args.n or s.n_records, s.seed)
        recs = build_records(tables, ids, salt=s.id_salt, synthetic=_is_synthetic(s.data_dir),
                             max_items=s.max_items_per_section, max_labs=s.max_labs)
    lex = lexicon(tables)
    checker = FaithfulnessChecker(lex)
    systems = _systems(args, s, lex)
    judge = _judge(args, s, checker, systems)
    result = run_benchmark(recs, systems, checker, judge)
    report = summarize(result, seed=s.seed)
    report.update({"records": len(recs), "synthetic": all(r.synthetic for r in recs),
                   "judge": getattr(judge, "name", None), "seed": s.seed})
    write_outputs(result, report, s.work_dir)
    print(json.dumps(report, indent=2))
    return 0


def cmd_agreement(args) -> int:
    rows = [json.loads(line) for line in Path(args.rows).read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(agreement(rows, read_ratings(Path(args.ratings))), indent=2))
    return 0


def cmd_demo(args) -> int:
    out = Path(args.out or "runs/demo")
    data = write_synthetic(out / "data")
    ns = argparse.Namespace(data_dir=str(data), out=str(out), command="run", records=None, n=40,
                            systems="template,hallucination,omission", judge="rule")
    return cmd_run(ns)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ehr2summary", description="Grounded discharge summaries and checked evaluation.")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("synth", help="write synthetic MIMIC-III style tables")
    sp.add_argument("--out", default="data/synthetic")
    sp.add_argument("--n", type=int, default=40)
    sp.add_argument("--seed", type=int, default=7)
    sp.set_defaults(func=cmd_synth)

    sp = sub.add_parser("records", help="build de-identified records for a seeded sample of admissions")
    sp.add_argument("--data-dir")
    sp.add_argument("--n", type=int)
    sp.add_argument("--out", default="runs/records.jsonl")
    sp.set_defaults(func=cmd_records)

    sp = sub.add_parser("run", help="generate, check and score summaries")
    sp.add_argument("--data-dir")
    sp.add_argument("--records", help="records.jsonl from 'ehr2summary records'")
    sp.add_argument("--n", type=int)
    sp.add_argument("--systems", default="template", help="comma list: template, hallucination, omission, llm")
    sp.add_argument("--judge", default="rule", choices=["rule", "llm", "llm-logprob", "none"])
    sp.add_argument("--out", help="output folder (default EHR2SUMMARY_WORK_DIR or runs)")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("agreement", help="judge-human correlation from rows.jsonl and a ratings CSV")
    sp.add_argument("--rows", required=True)
    sp.add_argument("--ratings", required=True)
    sp.set_defaults(func=cmd_agreement)

    sp = sub.add_parser("demo", help="offline demo on synthetic tables")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    try:
        return args.func(args)
    except (ConfigError, TableError, LLMError, PrivacyError, JudgeIndependenceError, ValueError,
            FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
