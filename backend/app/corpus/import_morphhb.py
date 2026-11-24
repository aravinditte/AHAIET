"""Corpus importer: Open Scriptures morphhb (WLC OSIS XML) + WEB alignment.

Usage (from backend/):
  python -m app.corpus.import_morphhb --download --import-db
  python -m app.corpus.import_morphhb --osis-dir <dir> --web-zip <zip> --out <jsonl>

Sources and licences (recorded per passage and in the datasets manifest):
- Westminster Leningrad Codex text: Public Domain.
- morphhb morphological annotations (Open Scriptures Hebrew Bible):
  CC BY 4.0 — https://github.com/openscriptures/morphhb
- World English Bible: Public Domain — https://ebible.org/eng-web/

Language assignment: Genesis is Hebrew. Daniel is assigned by the
documented Biblical Aramaic range Daniel 2:4b-7:28; word-level language
flags come from morphhb itself (morph codes prefixed 'H' = Hebrew,
'A' = Aramaic), so the Hebrew narration opening Daniel 2:4 keeps Hebrew
word flags inside an Aramaic-range verse, and that is recorded.

Partitions are assigned by book/chapter blocks, never by random verse
draw, so near-identical verses cannot leak across partitions:
Genesis chapters 1-25 -> train, 26-50 -> validation, Daniel -> test.
"""
from __future__ import annotations
import argparse, hashlib, io, json, re, sys, urllib.request, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services.language.normalize import normalize, normalize_nodiac  # noqa: E402
from app.storage import db as store  # noqa: E402

OSIS_NS = {"o": "http://www.bibletechnologies.net/2003/OSIS/namespace"}
MORPHHB_URLS = {
    "Gen": "https://raw.githubusercontent.com/openscriptures/morphhb/master/wlc/Gen.xml",
    "Dan": "https://raw.githubusercontent.com/openscriptures/morphhb/master/wlc/Dan.xml",
}
WEB_ZIP_URL = "https://ebible.org/Scriptures/eng-web_vpl.zip"
SOURCE_EDITION = "Westminster Leningrad Codex (WLC) via Open Scriptures morphhb (OSHB)"
TRANSLATION_EDITION = "World English Bible (WEB)"
SOURCE_LICENSE = "WLC text: Public Domain; morphhb annotations: CC BY 4.0"
ENGLISH_LICENSE = "World English Bible: Public Domain"
BOOK_NAMES = {"Gen": "Genesis", "Dan": "Daniel"}
WEB_BOOK_CODES = {"Gen": "GEN", "Dan": "DAN"}
VERSE_RE = re.compile(r"^(Gen|Dan)\.(\d+)\.(\d+)$")
WEB_LINE_RE = re.compile(r"^([A-Z0-9]{3}) (\d+):(\d+)[a-z]? (.*)$")

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _verse_language(book: str, chapter: int, verse: int) -> str:
    if book == "Dan":
        in_aramaic = (chapter == 2 and verse >= 4) or (3 <= chapter <= 6) or (chapter == 7 and verse <= 28)
        return "biblical_aramaic" if in_aramaic else "biblical_hebrew"
    return "biblical_hebrew"

def _partition(book: str, chapter: int) -> str:
    if book == "Dan":
        return "test"
    return "train" if chapter <= 25 else "validation"

def _strongs(lemma: str) -> str:
    if not lemma:
        return ""
    token = lemma.split()[0]
    if "/" in token:
        token = token.split("/")[-1]
    return token if token.isdigit() else ""

def parse_osis(path: Path, book: str) -> list[dict]:
    """Parse one morphhb OSIS book file into canonical passage dicts."""
    tree = ET.parse(path)
    root = tree.getroot()
    passages: list[dict] = []
    for verse_el in root.iter("{http://www.bibletechnologies.net/2003/OSIS/namespace}verse"):
        osis_id = verse_el.get("osisID") or ""
        m = VERSE_RE.match(osis_id)
        if not m:
            continue
        chapter, verse = int(m.group(2)), int(m.group(3))
        parts: list[str] = []
        words: list[dict] = []
        for child in verse_el:
            tag = child.tag.split("}")[-1]
            if tag == "w":
                raw = (child.text or "")
                surface = raw.replace("/", "")
                morph = child.get("morph") or ""
                lemma = child.get("lemma") or ""
                word_lang = {"H": "hebrew", "A": "aramaic"}.get(morph[:1], "")
                words.append({"surface": surface, "lemma": lemma,
                              "strongs": _strongs(lemma), "morph_code": morph,
                              "word_language": word_lang})
                if parts and not parts[-1].endswith(("־", " ")):
                    parts.append(" ")
                parts.append(surface)
            elif tag == "seg":
                seg_type = child.get("type") or ""
                if seg_type == "x-maqqef":
                    parts.append("־")
                elif seg_type == "x-sof-pasuq":
                    parts.append("׃")
                elif child.text:
                    parts.append(child.text)
            # <note> (ketiv/qere variants) is intentionally not merged into
            # the main surface text; the ketiv word in the main flow stands.
        source_text = "".join(parts).strip()
        language = _verse_language(book, chapter, verse)
        passages.append({
            "id": f"morphhb-{book.lower()}-{chapter}-{verse}",
            "language": language,
            "dialect": "biblical",
            "script": "Hebrew",
            "period": "biblical",
            "source_text": source_text,
            "english_text": "",
            "book": BOOK_NAMES[book],
            "reference": f"{BOOK_NAMES[book]} {chapter}:{verse}",
            "source_edition": SOURCE_EDITION,
            "translation_edition": TRANSLATION_EDITION,
            "license": SOURCE_LICENSE + "; " + ENGLISH_LICENSE,
            "provenance": f"morphhb OSIS file {path.name} (sha256 recorded in datasets manifest)",
            "partition": _partition(book, chapter),
            "words": words,
        })
    return passages

def parse_web_vpl(text: str) -> dict[tuple[str, int, int], str]:
    out: dict[tuple[str, int, int], str] = {}
    code_to_book = {v: k for k, v in WEB_BOOK_CODES.items()}
    for line in text.splitlines():
        m = WEB_LINE_RE.match(line.strip())
        if not m or m.group(1) not in code_to_book:
            continue
        book = code_to_book[m.group(1)]
        out[(book, int(m.group(2)), int(m.group(3)))] = m.group(4).strip()
    return out

def load_web(web_zip: Path | None, web_txt: Path | None) -> dict:
    if web_txt and web_txt.exists():
        return parse_web_vpl(web_txt.read_text(encoding="utf-8"))
    if web_zip and web_zip.exists():
        with zipfile.ZipFile(web_zip) as z:
            names = [n for n in z.namelist() if n.endswith("_vpl.txt")]
            if names:
                return parse_web_vpl(z.read(names[0]).decode("utf-8"))
    return {}

def build_corpus(osis_dir: Path, web_zip: Path | None, web_txt: Path | None) -> tuple[list[dict], dict]:
    web = load_web(web_zip, web_txt)
    passages: list[dict] = []
    seen: set[tuple] = set()
    report = {"files": {}, "verses_parsed": 0, "aligned_english": 0, "duplicates_skipped": 0,
              "validation_errors": [], "by_language": {}}
    for book in ("Gen", "Dan"):
        path = osis_dir / f"{book}.xml"
        if not path.exists():
            report["validation_errors"].append(f"missing OSIS file: {path}")
            continue
        report["files"][path.name] = {"sha256": sha256_file(path), "url": MORPHHB_URLS[book]}
        for p in parse_osis(path, book):
            report["verses_parsed"] += 1
            if not p["source_text"]:
                report["validation_errors"].append(f"empty source: {p['reference']}")
                continue
            ref_m = re.match(r"^(Genesis|Daniel) (\d+):(\d+)$", p["reference"])
            chapter, verse = int(ref_m.group(2)), int(ref_m.group(3))
            english = web.get((book, chapter, verse), "")
            p["english_text"] = english
            if english:
                report["aligned_english"] += 1
            key = (p["language"], p["reference"], normalize(p["source_text"]))
            if key in seen:
                report["duplicates_skipped"] += 1
                continue
            seen.add(key)
            report["by_language"][p["language"]] = report["by_language"].get(p["language"], 0) + 1
            passages.append(p)
    if web_zip and web_zip.exists():
        report["files"][web_zip.name] = {"sha256": sha256_file(web_zip), "url": WEB_ZIP_URL}
    return passages, report

def import_into_db(db_path: Path, passages: list[dict]) -> dict:
    store.migrate(db_path)
    conn = store.connect(db_path)
    try:
        conn.execute("DELETE FROM corpus_words WHERE passage_id IN (SELECT id FROM reference_passages WHERE source_edition=?)",
                     (SOURCE_EDITION,))
        conn.execute("DELETE FROM reference_passages WHERE source_edition=?", (SOURCE_EDITION,))
        n_words = 0
        for p in passages:
            conn.execute(
                "INSERT INTO reference_passages(id,language_profile,source_text,english_text,edition,license,provenance,"
                "dialect,script,period,book,reference,source_edition,translation_edition,partition_name,"
                "normalized_source,normalized_nodiac_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p["id"], p["language"], p["source_text"], p["english_text"], p["source_edition"],
                 p["license"], p["provenance"], p["dialect"], p["script"], p["period"], p["book"],
                 p["reference"], p["source_edition"], p["translation_edition"], p["partition"],
                 normalize(p["source_text"]), normalize_nodiac(p["source_text"])))
            for i, w in enumerate(p["words"]):
                conn.execute(
                    "INSERT INTO corpus_words(passage_id,language_profile,position,surface,surface_nodiac,lemma,strongs,morph_code,word_language)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (p["id"], p["language"], i, w["surface"], normalize_nodiac(w["surface"]),
                     w["lemma"], w["strongs"], w["morph_code"], w["word_language"]))
                n_words += 1
        conn.commit()
    finally:
        conn.close()
    # The retrieval service memoises verified-passage lookups in-process;
    # a fresh import must not be hidden behind a stale cached miss.
    try:
        from app.services.retrieval.service import invalidate_lookup_cache
        invalidate_lookup_cache()
    except Exception:
        pass
    return {"passages_imported": len(passages), "words_imported": n_words}

def download_sources(osis_dir: Path, corpus_dir: Path) -> None:
    osis_dir.mkdir(parents=True, exist_ok=True)
    for book, url in MORPHHB_URLS.items():
        dest = osis_dir / f"{book}.xml"
        if not dest.exists():
            urllib.request.urlretrieve(url, dest)
    web_zip = corpus_dir / "eng-web_vpl.zip"
    if not web_zip.exists():
        urllib.request.urlretrieve(WEB_ZIP_URL, web_zip)

def main(argv: list[str] | None = None) -> int:
    from app.core.config import settings
    ap = argparse.ArgumentParser(description="Import morphhb/WLC corpus with WEB alignment")
    ap.add_argument("--download", action="store_true", help="download any missing source files first")
    ap.add_argument("--osis-dir", type=Path, default=settings.corpus_dir / "morphhb")
    ap.add_argument("--web-zip", type=Path, default=settings.corpus_dir / "eng-web_vpl.zip")
    ap.add_argument("--web-txt", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=settings.corpus_dir / "passages.jsonl")
    ap.add_argument("--import-db", action="store_true", help="also import into the SQLite database")
    ap.add_argument("--db", type=Path, default=settings.db_path)
    ap.add_argument("--sample-out", type=Path, default=None, help="write a small fixture JSONL for the given --sample-refs")
    ap.add_argument("--sample-refs", default="Genesis 1:1,Genesis 1:2,Genesis 1:3,Daniel 2:4,Daniel 2:5,Daniel 7:9")
    args = ap.parse_args(argv)
    if args.download:
        download_sources(args.osis_dir, settings.corpus_dir)
    passages, report = build_corpus(args.osis_dir, args.web_zip, args.web_txt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for p in passages:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(json.dumps({"out": str(args.out), **report}, ensure_ascii=False, indent=2))
    if args.sample_out:
        wanted = {r.strip() for r in args.sample_refs.split(",")}
        sample = [p for p in passages if p["reference"] in wanted]
        args.sample_out.parent.mkdir(parents=True, exist_ok=True)
        with args.sample_out.open("w", encoding="utf-8") as fh:
            for p in sample:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
        print(f"sample passages written: {len(sample)} -> {args.sample_out}")
    if args.import_db:
        result = import_into_db(args.db, passages)
        print(json.dumps(result, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
