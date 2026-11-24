"""Prepare per-profile parallel corpora for SMT/NMT training.

Input: the canonical corpus JSONL written by the corpus importer
(backend/app/corpus/import_morphhb.py; default
artifacts/corpora/passages.jsonl). Each row carries: id, language,
dialect, script, period, source_text, english_text, book, reference,
source_edition, translation_edition, license, provenance, partition,
words[].

Output (default training/datasets/prepared/<profile>/):
  train.source.vocalized.txt / train.source.consonantal.txt / train.target.txt
  validation.* / test.*  (same three views; one verse per line, aligned)
  test.references.jsonl / validation.references.jsonl
      (source, English reference, reference string, editions, licence —
      the evaluation harness consumes these so metrics always cite the
      exact held-out rows)
  vocabulary.source.txt / vocabulary.target.txt (training-split tokens)
  dataset_card.json   (counts, checksums, editions, licences, strategy)
  leakage_report.json (cross-split duplicate / near-duplicate findings)

Split strategy: the importer's recorded group strategy is reused, not
reinvented — the corpus rows already carry a `partition` assigned by
book/chapter blocks (Genesis chapters 1-25 train, 26-50 validation,
Daniel held out as test; see artifacts/manifests/datasets.json). This
script verifies that no (book, chapter) group spans two splits, then
writes the splits per language profile, separately. A consequence of
the recorded strategy is stated plainly in the report: every Aramaic
passage sits in the Daniel test partition, so the Aramaic profile has
no training or validation rows until the strategy is deliberately
revised or more Aramaic books are imported.

Leakage rules:
- an exact duplicate (normalized source key) appearing in two splits
  of the same profile is a hard failure (exit code 2);
- a diacritic-insensitive duplicate across splits is also a hard
  failure (it is the same verse in a different pointing);
- near-duplicates across splits (token-set Jaccard >= threshold) are
  flagged in leakage_report.json as warnings, not silently dropped;
- duplicates inside one split are removed and counted.

Verses with empty English (WLC/WEB numbering differences) are excluded
from the parallel files and counted in the dataset card — never
silently dropped and never aligned to a neighbouring verse.

Usage:
  python training/datasets/prepare_parallel.py \
      [--corpus artifacts/corpora/passages.jsonl] \
      [--out-dir training/datasets/prepared] \
      [--profiles biblical_hebrew biblical_aramaic]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.language.normalize import normalize, normalize_nodiac  # noqa: E402
from app.services.language.tokenize import tokenize_target  # noqa: E402

# The sibling tokenize.py shadows the stdlib module name, so load it by
# file path under a private module name instead of a plain import.
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("ahaiet_datasets_tokenize", Path(__file__).with_name("tokenize.py"))
_tokenize_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_tokenize_mod)
tokenize_source_view = _tokenize_mod.tokenize_source_view
from training.common.manifest import DATASETS_MANIFEST, REPO_ROOT, load_json, sha256_file  # noqa: E402

PROFILES = ("biblical_hebrew", "biblical_aramaic")
SPLITS = ("train", "validation", "test")
DEFAULT_SEED = 13  # recorded for reproducibility; splits are group-determined, no RNG is used
DEFAULT_SMALL_CORPUS_THRESHOLD = 1000
DEFAULT_NEAR_DUP_THRESHOLD = 0.9
_REF_RE = re.compile(r"^(.+?) (\d+):(\d+)$")


class LeakageError(Exception):
    """Raised when a hard leakage rule is violated."""


def chapter_block(passage: dict) -> tuple[str, int]:
    """The passage-group key: (book, chapter). Groups never span splits."""
    m = _REF_RE.match(passage.get("reference", ""))
    if m:
        return m.group(1), int(m.group(2))
    return passage.get("book", ""), -1


def load_corpus(path: Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def recorded_split_strategy() -> str:
    """The partition strategy recorded in the datasets manifest."""
    try:
        manifest = load_json(DATASETS_MANIFEST)
    except Exception:
        return ""
    parts = [d.get("partition_strategy", "") for d in manifest.get("datasets", [])]
    return " | ".join(p for p in parts if p)


def check_group_integrity(passages: list[dict]) -> None:
    block_to_split: dict[tuple, str] = {}
    for p in passages:
        block = chapter_block(p)
        split = p.get("partition", "")
        if block in block_to_split and block_to_split[block] != split:
            raise LeakageError(
                f"passage group {block} spans splits '{block_to_split[block]}' and '{split}'; "
                "the recorded group split strategy has been violated")
        block_to_split[block] = split


def _token_jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def check_leakage(profile_rows: dict[str, list[dict]],
                  near_dup_threshold: float = DEFAULT_NEAR_DUP_THRESHOLD) -> dict:
    """Cross-split leakage checks for one profile's split rows.

    Returns the leakage report dict. Raises LeakageError on exact or
    diacritic-insensitive duplicates across splits.
    """
    report = {"exact_cross_split_duplicates": [], "nodiac_cross_split_duplicates": [],
              "near_duplicates": [], "near_dup_threshold": near_dup_threshold}
    keys: dict[str, dict[str, str]] = {"exact": {}, "nodiac": {}}
    split_tokens: dict[str, list[tuple[str, set]]] = {}
    for split, rows in profile_rows.items():
        split_tokens[split] = []
        for p in rows:
            exact_key = normalize(p["source_text"])
            nodiac_key = normalize_nodiac(p["source_text"])
            for kind, key in (("exact", exact_key), ("nodiac", nodiac_key)):
                other = keys[kind].get(key)
                if other is not None and other != split:
                    report[f"{kind}_cross_split_duplicates"].append(
                        {"reference": p["reference"], "splits": sorted([other, split])})
                keys[kind].setdefault(key, split)
            split_tokens[split].append((p["reference"], set(tokenize_source_view(p["source_text"], "consonantal"))))
    if report["exact_cross_split_duplicates"]:
        raise LeakageError("exact cross-split duplicates found: "
                           + json.dumps(report["exact_cross_split_duplicates"], ensure_ascii=False))
    if report["nodiac_cross_split_duplicates"]:
        raise LeakageError("diacritic-insensitive cross-split duplicates found: "
                           + json.dumps(report["nodiac_cross_split_duplicates"], ensure_ascii=False))
    split_names = list(split_tokens)
    for i, a in enumerate(split_names):
        for b in split_names[i + 1:]:
            for ref_a, toks_a in split_tokens[a]:
                for ref_b, toks_b in split_tokens[b]:
                    score = _token_jaccard(toks_a, toks_b)
                    if score >= near_dup_threshold:
                        report["near_duplicates"].append(
                            {"a": {"split": a, "reference": ref_a},
                             "b": {"split": b, "reference": ref_b},
                             "token_jaccard": round(score, 4)})
    return report


def _write_lines(path: Path, lines: list[str]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(line + "\n" for line in lines)
    path.write_text(text, encoding="utf-8")
    return {"path": path.name, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "lines": len(lines)}


def prepare_profile(profile: str, passages: list[dict], out_dir: Path,
                    *, small_corpus_threshold: int = DEFAULT_SMALL_CORPUS_THRESHOLD,
                    near_dup_threshold: float = DEFAULT_NEAR_DUP_THRESHOLD,
                    seed: int = DEFAULT_SEED,
                    corpus_sha256: str = "", split_strategy: str = "") -> dict:
    """Write one profile's parallel files + dataset card. Returns the card."""
    rows = [p for p in passages if p.get("language") == profile]
    excluded_empty_english = [p for p in rows if not (p.get("english_text") or "").strip()]
    usable = [p for p in rows if (p.get("english_text") or "").strip()]
    by_split: dict[str, list[dict]] = {s: [] for s in SPLITS}
    seen_within: set[tuple[str, str]] = set()
    duplicates_within_split = 0
    for p in usable:
        split = p.get("partition") or "train"
        if split not in by_split:
            raise LeakageError(f"passage {p.get('reference')} has unknown partition '{split}'")
        key = (split, normalize(p["source_text"]))
        if key in seen_within:
            duplicates_within_split += 1
            continue
        seen_within.add(key)
        by_split[split].append(p)
    leakage = check_leakage(by_split, near_dup_threshold)
    out_dir.mkdir(parents=True, exist_ok=True)
    split_cards: dict[str, dict] = {}
    vocab_source: Counter = Counter()
    vocab_target: Counter = Counter()
    for split, split_rows in by_split.items():
        files = {}
        views = {
            "vocalized": [tokenize_source_view(p["source_text"], "vocalized") for p in split_rows],
            "consonantal": [tokenize_source_view(p["source_text"], "consonantal") for p in split_rows],
        }
        targets = [tokenize_target(p["english_text"]) for p in split_rows]
        files[f"{split}.source.vocalized.txt"] = _write_lines(
            out_dir / f"{split}.source.vocalized.txt", [" ".join(t) for t in views["vocalized"]])
        files[f"{split}.source.consonantal.txt"] = _write_lines(
            out_dir / f"{split}.source.consonantal.txt", [" ".join(t) for t in views["consonantal"]])
        files[f"{split}.target.txt"] = _write_lines(
            out_dir / f"{split}.target.txt", [" ".join(t) for t in targets])
        if split in ("validation", "test"):
            refs = [{"reference": p["reference"], "book": p["book"],
                     "language": p["language"], "source_text": p["source_text"],
                     "english_text": p["english_text"],
                     "source_edition": p["source_edition"],
                     "translation_edition": p["translation_edition"],
                     "license": p["license"], "provenance": p["provenance"]}
                    for p in split_rows]
            ref_text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in refs)
            ref_path = out_dir / f"{split}.references.jsonl"
            ref_path.write_text(ref_text, encoding="utf-8")
            files[ref_path.name] = {"path": ref_path.name,
                                    "sha256": hashlib.sha256(ref_text.encode("utf-8")).hexdigest(),
                                    "lines": len(refs)}
        if split == "train":
            for toks in views["vocalized"]:
                vocab_source.update(toks)
            for toks in targets:
                vocab_target.update(toks)
        split_cards[split] = {
            "pairs": len(split_rows),
            "source_tokens_vocalized": sum(len(t) for t in views["vocalized"]),
            "source_tokens_consonantal": sum(len(t) for t in views["consonantal"]),
            "target_tokens": sum(len(t) for t in targets),
            "files": files,
        }
    _write_lines(out_dir / "vocabulary.source.txt", sorted(vocab_source))
    _write_lines(out_dir / "vocabulary.target.txt", sorted(vocab_target))
    train_pairs = split_cards["train"]["pairs"]
    is_small = train_pairs < small_corpus_threshold
    small_statement = None
    if is_small:
        small_statement = (
            f"This profile has {train_pairs} training pairs, below the configured "
            f"small-corpus threshold of {small_corpus_threshold}. A model trained on "
            "this little data is a baseline for measurement only; generalisation to "
            "unseen historical text is not expected and must not be claimed.")
    card = {
        "profile": profile,
        "generated_by": "training/datasets/prepare_parallel.py",
        "seed": seed,
        "corpus": {"input_sha256": corpus_sha256, "passages_for_profile": len(rows),
                   "excluded_empty_english": len(excluded_empty_english),
                   "excluded_empty_english_references": [p["reference"] for p in excluded_empty_english],
                   "duplicates_within_split_removed": duplicates_within_split},
        "splits": split_cards,
        "source_editions": sorted({p["source_edition"] for p in rows}),
        "translation_editions": sorted({p["translation_edition"] for p in rows}),
        "licenses": sorted({p["license"] for p in rows}),
        "split_strategy": split_strategy or
            "Importer group strategy: Genesis chapters 1-25 train, 26-50 validation, Daniel test (book/chapter blocks, no random verse-level split).",
        "views": {
            "vocalized": "Canonical source text with niqqud/cantillation preserved; the default training and inference view.",
            "consonantal": "Diacritic-stripped view (normalize_nodiac) for comparison experiments; clearly a derived view, never the canonical text.",
        },
        "small_corpus": {"is_small": is_small, "threshold": small_corpus_threshold,
                         "train_pairs": train_pairs, "statement": small_statement},
        "leakage_report": "leakage_report.json",
    }
    (out_dir / "dataset_card.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "leakage_report.json").write_text(
        json.dumps(leakage, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    card["_leakage"] = leakage
    return card


def run(corpus_path: Path, out_dir: Path, profiles: tuple[str, ...] = PROFILES,
        **kwargs) -> dict:
    passages = load_corpus(corpus_path)
    check_group_integrity(passages)
    corpus_sha = sha256_file(corpus_path)
    strategy = recorded_split_strategy()
    report: dict = {"corpus": str(corpus_path), "corpus_sha256": corpus_sha,
                    "total_passages": len(passages), "profiles": {}}
    for profile in profiles:
        card = prepare_profile(profile, passages, out_dir / profile,
                               corpus_sha256=corpus_sha, split_strategy=strategy, **kwargs)
        report["profiles"][profile] = {
            "pairs_per_split": {s: card["splits"][s]["pairs"] for s in SPLITS},
            "excluded_empty_english": card["corpus"]["excluded_empty_english"],
            "small_corpus": card["small_corpus"]["is_small"],
            "near_duplicates_flagged": len(card["_leakage"]["near_duplicates"]),
        }
        if profile == "biblical_aramaic" and card["splits"]["train"]["pairs"] == 0:
            report["profiles"][profile]["data_statement"] = (
                "All Aramaic passages sit in the held-out Daniel test partition under "
                "the recorded split strategy, so this profile currently has no training "
                "or validation data. SMT/NMT training for this profile cannot proceed "
                "until the split strategy is deliberately revised or more Aramaic books "
                "are imported; the prepared test files exist for evaluation only.")
    (out_dir / "prep_report.json").parent.mkdir(parents=True, exist_ok=True)
    (out_dir / "prep_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prepare per-profile parallel corpora (see module docstring)")
    ap.add_argument("--corpus", type=Path, default=REPO_ROOT / "artifacts" / "corpora" / "passages.jsonl")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "training" / "datasets" / "prepared")
    ap.add_argument("--profiles", nargs="+", default=list(PROFILES))
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--small-corpus-threshold", type=int, default=DEFAULT_SMALL_CORPUS_THRESHOLD)
    ap.add_argument("--near-dup-threshold", type=float, default=DEFAULT_NEAR_DUP_THRESHOLD)
    args = ap.parse_args(argv)
    if not args.corpus.exists():
        print(f"Canonical corpus not found: {args.corpus}\n"
              "Run the corpus importer first (scripts/import-corpus.ps1 or "
              "python -m app.corpus.import_morphhb from backend/).", file=sys.stderr)
        return 3
    try:
        report = run(args.corpus, args.out_dir, tuple(args.profiles), seed=args.seed,
                     small_corpus_threshold=args.small_corpus_threshold,
                     near_dup_threshold=args.near_dup_threshold)
    except LeakageError as e:
        print(f"LEAKAGE CHECK FAILED: {e}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
