"""Shared translation evaluation harness.

Runs every AVAILABLE engine over the SAME held-out test split for one
language profile and writes:
  artifacts/benchmarks/<profile>-translation-eval.json
  artifacts/benchmarks/<profile>-translation-eval.md

Engines, in report order:
  1. dictionary_gloss_baseline — word-by-word lemma/Strong's glossing
     from the corpus word index (training/evaluation/
     dictionary_baseline.py). Labelled "not a sentence translation"
     everywhere; it is the lexical floor, nothing more.
  2. Moses SMT — via the backend adapter code path
     (app.services.translation.moses_adapter), so the number measures
     exactly what the API would serve.
  3. Marian NMT — via the backend adapter code path likewise.
  4. retrieval baseline — verified corpus lookup (exact/normalized) of
     each test source against the imported database. CAVEAT, printed in
     every report: the test verses come from the same corpus the
     retrieval index is built from, so retrieval coverage here is an
     UPPER-BOUND reference figure, not a measure of performance on
     unseen text.

Metrics: SacreBLEU + chrF++ from sacrebleu when installed; otherwise
the pure-Python fallbacks in text_metrics.py, labelled as fallbacks
(chrF, not chrF++; approximate BLEU). Plus per-engine mean/p95 latency,
source-token coverage, and the worst-scoring failure examples with
source/reference/hypothesis. An unavailable engine is listed with its
status and the reason — its scores are null, never zero-filled.

Selection record: with --write-selection (default), the trained engine
with the highest recorded chrF++ is written into its model card
(metrics + selection block) and into the models manifest entry, and the
other trained engine's selection is marked not-selected. This record is
what the backend selection service reads; it is written only from a
real harness run, never by hand.

Usage:
  python training/evaluation/evaluate_translation.py --profile biblical_hebrew
  python training/evaluation/evaluate_translation.py --profile biblical_aramaic --no-write-selection
"""
from __future__ import annotations
import argparse
import hashlib
import json
import statistics
import sys
import time
import uuid
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))

from app.core.config import Settings  # noqa: E402
from app.services import retrieval  # noqa: E402
from app.services.translation import marian_adapter, model_artifacts, moses_adapter  # noqa: E402
from app.services.translation.service import load_models_manifest  # noqa: E402
from training.common.manifest import load_json, write_json  # noqa: E402
from training.evaluation import dictionary_baseline, text_metrics  # noqa: E402

PROFILES = ("biblical_hebrew", "biblical_aramaic")
# AHAIET-005: a held-out test partition smaller than this cannot
# support a score or a model-selection record. Configurable via
# --min-test-pairs; the default is documented in docs/MODEL_EVALUATION.md.
DEFAULT_MIN_TEST_PAIRS = 10
RETRIEVAL_CAVEAT = ("Retrieval coverage on this split is an upper-bound reference figure: "
                    "the test verses come from the same corpus the retrieval index is built "
                    "from, so a match here does not indicate performance on unseen text.")


def load_test_pairs(prepared_dir: Path, profile: str, corpus_path: Path) -> list[dict]:
    refs = prepared_dir / profile / "test.references.jsonl"
    if refs.exists():
        return [json.loads(l) for l in refs.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [json.loads(l) for l in corpus_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [p for p in rows if p.get("language") == profile and p.get("partition") == "test"
            and (p.get("english_text") or "").strip()]


def metric_impl() -> tuple[str, object]:
    try:
        import sacrebleu  # noqa: F401
        return "sacrebleu", sacrebleu
    except Exception:
        return "pure-python fallback (chrF, not chrF++; approximate BLEU)", None


def metric_signature(impl) -> str:
    """Implementation signature recorded with every score
    (AHAIET-006): scores are comparable only when this string, the
    test-set sha256, and the sample count all match."""
    if impl is not None:
        try:
            import sacrebleu
            version = sacrebleu.__version__
        except Exception:
            version = "unknown"
        return f"sacrebleu-{version}:CHRF(word_order=2)+BLEU"
    return "pure-python-fallback:chrf+approx-bleu"


def test_set_sha256(pairs: list[dict]) -> str:
    material = "\n".join(f"{p.get('source_text','')}\t{p.get('english_text','')}" for p in pairs)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def corpus_sha256(corpus_path: Path) -> str | None:
    if not corpus_path.exists():
        return None
    return hashlib.sha256(corpus_path.read_bytes()).hexdigest()


def score(hypotheses: list[str], references: list[str], impl) -> dict:
    if impl is not None:
        bleu = impl.metrics.BLEU().corpus_score(hypotheses, [references])
        chrf = impl.metrics.CHRF(word_order=2).corpus_score(hypotheses, [references])
        return {"sacrebleu": round(bleu.score, 2), "chrf_pp": round(chrf.score, 2),
                "metric": "chrf_pp", "chrf_scale": "0-100 (sacrebleu chrF++)"}
    # AHAIET-006: the fallback computes chrF, NOT chrF++. It is recorded
    # under the key "chrf" with metric "chrf" and is never comparable
    # with sacrebleu chrF++ scores (different metric signature).
    return {"sacrebleu": round(text_metrics.corpus_bleu(hypotheses, references) * 100, 2),
            "chrf": round(text_metrics.corpus_chrf(hypotheses, references) * 100, 2),
            "metric": "chrf",
            "chrf_scale": "0-100 (fallback chrF rescaled; not chrF++)"}


def sentence_chrf(hypothesis: str, reference: str, impl) -> float:
    if impl is not None:
        return impl.metrics.CHRF(word_order=2).sentence_score(hypothesis, [reference]).score / 100.0
    return text_metrics.chrf_sentence(hypothesis, reference)


def _latency(samples: list[float]) -> dict:
    if not samples:
        return {"mean_ms": None, "p95_ms": None}
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {"mean_ms": round(statistics.mean(samples) * 1000, 1),
            "p95_ms": round(p95 * 1000, 1)}


def _failures(pairs: list[dict], hypotheses: list[str], impl, limit: int = 5) -> list[dict]:
    scored = []
    for pair, hyp in zip(pairs, hypotheses):
        scored.append({"reference": pair["reference"],
                       "source": pair["source_text"],
                       "reference_english": pair["english_text"],
                       "hypothesis": hyp,
                       "sentence_chrf": round(sentence_chrf(hyp, pair["english_text"], impl), 4)})
    scored.sort(key=lambda f: f["sentence_chrf"])
    return scored[:limit]


def _coverage_mean(coverages: list[dict | None]) -> dict | None:
    known = [c for c in coverages if c]
    if not known:
        return None
    total_src = sum(c["source_tokens"] for c in known)
    total_known = sum(c["known_tokens"] for c in known)
    return {"source_tokens": total_src, "known_tokens": total_known,
            "coverage_ratio": round(total_known / total_src, 4) if total_src else 1.0,
            "oov_words": sorted({w for c in known for w in c.get("oov_words", [])})}


def run_engine_adapter(adapter, entry: dict, pairs: list[dict], settings: Settings,
                       impl) -> dict:
    resolution = model_artifacts.resolve_entry(entry)
    if not resolution.ok:
        return {"status": "unavailable",
                "reason": "artifact incomplete — missing: " + "; ".join(resolution.missing)}
    hypotheses, latencies, coverages = [], [], []
    try:
        for pair in pairs:
            start = time.perf_counter()
            result = adapter.run(entry, pair["source_text"], settings)
            latencies.append(time.perf_counter() - start)
            hypotheses.append(result["english_translation"])
            coverages.append(result.get("coverage"))
    except Exception as e:  # decoder binary missing, timeout, non-zero exit
        return {"status": "unavailable", "reason": f"{type(e).__name__}: {e}"}
    references = [p["english_text"] for p in pairs]
    return {"status": "evaluated", "metrics": score(hypotheses, references, impl),
            "latency": _latency(latencies), "coverage": _coverage_mean(coverages),
            "model_version": resolution.model_version,
            "artifact_sha256": resolution.artifact_sha256,
            "evaluation_run": {"run_id": uuid.uuid4().hex,
                               "test_set_sha256": test_set_sha256(pairs),
                               "sample_count": len(pairs),
                               "metric_signature": metric_signature(impl),
                               "artifact_sha256": resolution.artifact_sha256,
                               "date": date.today().isoformat()},
            "failures": _failures(pairs, hypotheses, impl)}


def evaluate(profile: str, prepared_dir: Path, corpus_path: Path, db_path: Path,
             settings: Settings, min_test_pairs: int = DEFAULT_MIN_TEST_PAIRS) -> dict:
    pairs = load_test_pairs(prepared_dir, profile, corpus_path)
    impl_name, impl = metric_impl()
    references = [p["english_text"] for p in pairs]
    report: dict = {
        "profile": profile, "generated_by": "training/evaluation/evaluate_translation.py",
        "date": date.today().isoformat(), "test_pairs": len(pairs),
        "metric_implementation": impl_name,
        "metric_signature": metric_signature(impl),
        "test_set_sha256": test_set_sha256(pairs),
        "corpus_sha256": corpus_sha256(corpus_path),
        "split": "held-out test partition (book-group split — see dataset card)",
        "engines": {},
    }
    # AHAIET-005 gate: an empty or below-minimum test partition yields
    # NO scores and blocks selection writing entirely.
    if len(pairs) < min_test_pairs:
        report["status"] = "insufficient_test_data"
        report["reason"] = (f"held-out test partition has {len(pairs)} pair(s); the configured "
                            f"minimum is {min_test_pairs} (--min-test-pairs). No scores were "
                            "computed and no model selection may be written from this run.")
        for name in ("dictionary_gloss_baseline", "moses", "marian", "retrieval"):
            report["engines"][name] = {"status": "insufficient_test_data",
                                       "reason": report["reason"]}
        return report
    report["status"] = "evaluated"
    # 1. dictionary/rule baseline — lexicon built ONLY from the
    # training partition (AHAIET-004); split + corpus hash recorded.
    if corpus_path.exists() and pairs:
        lexicon = dictionary_baseline.load_lexicon_from_corpus(corpus_path, profile,
                                                               partitions={"train"})
        report["dictionary_baseline"] = {
            "lexicon_partitions": ["train"],
            "corpus_sha256": report["corpus_sha256"],
            "caveat": ("The dictionary baseline's lexicon is built only from training-partition "
                       "rows; held-out test vocabulary is out-of-vocabulary for it by "
                       "construction. " + dictionary_baseline.LABEL + ".")}
        hypotheses, coverages, latencies = [], [], []
        for pair in pairs:
            start = time.perf_counter()
            gloss, info = dictionary_baseline.gloss_text(pair["source_text"], lexicon)
            latencies.append(time.perf_counter() - start)
            hypotheses.append(gloss)
            coverages.append(info)
        report["engines"]["dictionary_gloss_baseline"] = {
            "label": dictionary_baseline.LABEL, "status": "evaluated",
            "lexicon_partitions": ["train"], "corpus_sha256": report["corpus_sha256"],
            "metrics": score(hypotheses, references, impl), "latency": _latency(latencies),
            "coverage": _coverage_mean(coverages), "failures": _failures(pairs, hypotheses, impl)}
    else:
        report["engines"]["dictionary_gloss_baseline"] = {
            "label": dictionary_baseline.LABEL, "status": "unavailable",
            "reason": "canonical corpus JSONL not found; run the corpus importer first"}
    # 2./3. trained engines via the backend adapter code path
    manifest = load_models_manifest(settings)
    entries = {e.get("engine"): e for e in manifest.get("models", [])
               if e.get("kind") == "translation" and e.get("language_profile") == profile}
    for engine, adapter in (("moses", moses_adapter), ("marian", marian_adapter)):
        entry = entries.get(engine)
        if entry is None:
            report["engines"][engine] = {"status": "unavailable",
                                         "reason": "no manifest entry for this profile"}
        else:
            report["engines"][engine] = run_engine_adapter(adapter, entry, pairs, settings, impl)
    # 4. retrieval baseline
    if pairs and db_path.exists():
        hypotheses, latencies, matched = [], [], 0
        for pair in pairs:
            start = time.perf_counter()
            result = retrieval.lookup(db_path, pair["source_text"], profile)
            latencies.append(time.perf_counter() - start)
            if result["match"] is not None:
                matched += 1
                hypotheses.append(result["match"]["english_text"])
            else:
                hypotheses.append("")
        report["engines"]["retrieval"] = {
            "status": "evaluated", "metrics": score(hypotheses, references, impl),
            "latency": _latency(latencies),
            "coverage": {"matched": matched, "pairs": len(pairs),
                         "match_rate": round(matched / len(pairs), 4) if pairs else 0.0},
            "caveat": RETRIEVAL_CAVEAT, "failures": _failures(pairs, hypotheses, impl)}
    else:
        report["engines"]["retrieval"] = {"status": "unavailable",
                                          "reason": "corpus database not imported/found",
                                          "caveat": RETRIEVAL_CAVEAT}
    return report


def write_selection(report: dict, settings: Settings) -> dict | None:
    """Record the winning trained engine in its model card + manifest.

    Refuses (returns None and writes nothing) when the report is gated
    insufficient_test_data (AHAIET-005), and compares only scores that
    carry an evaluation-run record with THIS report's test-set sha256
    and metric signature and a chrF++ value (AHAIET-006): fallback chrF
    scores are not comparable and can never drive selection."""
    if report.get("status") == "insufficient_test_data":
        return None
    candidates = []
    for engine in ("moses", "marian"):
        result = report["engines"].get(engine, {})
        run = result.get("evaluation_run") or {}
        metrics = result.get("metrics") or {}
        if (result.get("status") == "evaluated" and metrics.get("chrf_pp") is not None
                and run.get("test_set_sha256") == report.get("test_set_sha256")
                and run.get("metric_signature") == report.get("metric_signature")):
            candidates.append((engine, metrics["chrf_pp"]))
    if not candidates:
        return None
    winner, winner_chrf = max(candidates, key=lambda c: c[1])
    manifest = load_models_manifest(settings)
    for entry in manifest.get("models", []):
        if entry.get("kind") != "translation" or entry.get("language_profile") != report["profile"]:
            continue
        is_winner = entry.get("engine") == winner
        entry["selection"] = {"selected": is_winner, "metric": "chrf_pp",
                              "value": winner_chrf if is_winner else None,
                              "date": report["date"],
                              "evaluated_by": "training/evaluation/evaluate_translation.py",
                              "test_pairs": report["test_pairs"],
                              "run": report["engines"][winner].get("evaluation_run")}
        # Stale-metric hygiene: a previous evaluation record that does
        # not belong to this run's test set is versioned aside, never
        # left in place to be read as current (AHAIET-006).
        old_eval = entry.get("evaluation")
        if isinstance(old_eval, dict):
            old_run = old_eval.get("run") or {}
            if old_run.get("test_set_sha256") != report.get("test_set_sha256"):
                entry["evaluation_stale"] = old_eval
                entry.pop("evaluation", None)
        if is_winner:
            entry["evaluation"] = {"chrf_pp": winner_chrf, "date": report["date"],
                                   "test_pairs": report["test_pairs"],
                                   "run": report["engines"][winner].get("evaluation_run")}
            resolution = model_artifacts.resolve_entry(entry)
            if resolution.artifact_dir is not None:
                card_path = resolution.artifact_dir / "model_card.json"
                if card_path.exists():
                    card = load_json(card_path)
                    card["metrics"] = {"chrf_pp": winner_chrf,
                                       "sacrebleu": report["engines"][winner]["metrics"]["sacrebleu"],
                                       "metric_implementation": report["metric_implementation"],
                                       "test_pairs": report["test_pairs"], "date": report["date"]}
                    card["evaluation_run"] = report["engines"][winner].get("evaluation_run")
                    card["selection"] = entry["selection"]
                    write_json(card_path, card)
    write_json(settings.models_manifest, manifest)
    return {"winner": winner, "chrf_pp": winner_chrf}


def render_markdown(report: dict, selection_record: dict | None) -> str:
    lines = [f"# Translation evaluation — {report['profile']}", "",
             f"- Date: {report['date']}",
             f"- Test split: {report['split']}",
             f"- Test pairs: {report['test_pairs']}",
             f"- Metric implementation: {report['metric_implementation']}",
             "- Automatic metrics are not proof of exact meaning; pair them with the "
             "human review template (training/evaluation/human_review_template.md).", ""]
    lines += ["| Engine | Status | SacreBLEU | chrF++ | Latency mean / p95 (ms) | Coverage |",
              "|---|---|---|---|---|---|"]
    for name, result in report["engines"].items():
        if result.get("status") == "evaluated":
            m = result["metrics"]
            cov = result.get("coverage") or {}
            cov_text = (f"match rate {cov['match_rate']}" if "match_rate" in cov
                        else f"{cov.get('coverage_ratio', '—')}")
            lines.append(f"| {name} | evaluated | {m['sacrebleu']} | {m.get('chrf_pp', m.get('chrf'))} | "
                         f"{result['latency']['mean_ms']} / {result['latency']['p95_ms']} | {cov_text} |")
        else:
            lines.append(f"| {name} | unavailable | — | — | — | {result.get('reason', '')} |")
    lines.append("")
    if "retrieval" in report["engines"]:
        lines += [f"> {RETRIEVAL_CAVEAT}", ""]
    if report["engines"].get("dictionary_gloss_baseline", {}).get("label"):
        lines += [f"> {dictionary_baseline.LABEL}: word-by-word lemma/Strong's glosses; "
                  "its scores are a lexical floor, not translation quality.", ""]
    if selection_record:
        lines += [f"**Selected engine for this profile:** {selection_record['winner']} "
                  f"(recorded chrF++ {selection_record['chrf_pp']}). The record was written "
                  "into the model card and the models manifest by this run.", ""]
    else:
        lines += ["**Selected engine:** none recorded — no trained engine was evaluated in "
                  "this run, so the backend keeps its documented default order and honest "
                  "unavailable states.", ""]
    for name, result in report["engines"].items():
        if result.get("failures"):
            lines += [f"## Failure examples — {name} (lowest sentence chrF)", ""]
            for f in result["failures"]:
                lines += [f"- **{f['reference']}** (chrF {f['sentence_chrf']})",
                          f"  - source: {f['source']}",
                          f"  - reference: {f['reference_english']}",
                          f"  - hypothesis: {f['hypothesis']}"]
            lines.append("")
    lines += ["## Reproduction", "",
              "```bash",
              f"python training/evaluation/evaluate_translation.py --profile {report['profile']}",
              "```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate translation engines on the held-out test split")
    ap.add_argument("--profile", choices=PROFILES, required=True)
    ap.add_argument("--prepared-dir", type=Path,
                    default=REPO_ROOT / "training" / "datasets" / "prepared")
    ap.add_argument("--corpus", type=Path, default=REPO_ROOT / "artifacts" / "corpora" / "passages.jsonl")
    ap.add_argument("--db", type=Path, default=REPO_ROOT / "backend" / "data" / "ahaiet.db")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "artifacts" / "benchmarks")
    ap.add_argument("--no-write-selection", action="store_true",
                    help="do not write the winning-engine record into model cards/manifest")
    ap.add_argument("--min-test-pairs", type=int, default=DEFAULT_MIN_TEST_PAIRS,
                    help="minimum held-out test pairs required before any score or "
                         "selection is produced (AHAIET-005 gate)")
    args = ap.parse_args(argv)
    settings = Settings.from_env()
    report = evaluate(args.profile, args.prepared_dir, args.corpus, args.db, settings,
                      min_test_pairs=args.min_test_pairs)
    selection_record = None
    if not args.no_write_selection:
        selection_record = write_selection(report, settings)
    report["selection_record"] = selection_record
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / f"{args.profile}-translation-eval.json"
    md_path = args.out_dir / f"{args.profile}-translation-eval.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report, selection_record), encoding="utf-8")
    print(f"wrote {json_path}\nwrote {md_path}")
    for name, result in report["engines"].items():
        print(f"  {name}: {result.get('status')}"
              + (f" (chrF++ {result['metrics']['chrf_pp']})" if result.get("metrics", {}).get("chrf_pp") is not None else
                 f" — {result.get('reason', '')}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
