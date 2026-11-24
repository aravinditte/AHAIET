"""Unit tests: text processing, morphology separation, passage matching,
input validation, OCR TSV parsing, model selection, error envelope.

Written to be run by the developer (docs/VERIFICATION.md). None of these
need a provisioned engine or model: the OCR test feeds the TSV *parser*
a recorded fixture string (a parser fixture, not OCR output), and the
corpus tests import the committed six-passage fixture into a temporary
database, exactly like tests/test_corpus_ocr.py.
"""
import io, json, sys
from dataclasses import replace
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app.core.errors import ValidationAppError
from app.corpus.import_morphhb import import_into_db
from app.services.language.normalize import normalize, normalize_nodiac, tokens
from app.services.language.passage import split_segments, reassemble
from app.services.language.service import suggest_language
from app.services.language.tokenize import tokenize_source, tokenize_target
from app.services.morphology import analyze
from app.services.ocr.tesseract_adapter import parse_tsv
from app.services.preprocessing.service import validate_and_decode
from app.services import retrieval
from app.services.translation import selection
from conftest import png_bytes

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "training" / "datasets" / "fixtures" / "sample_passages.jsonl"

GEN_1_1 = "בְּרֵאשִׁית בָּרָא אֱלֹהִים אֵת הַשָּׁמַיִם וְאֵת הָאָרֶץ׃"


def _sample() -> dict[str, dict]:
    out = {}
    for line in SAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            p = json.loads(line)
            out[p["reference"]] = p
    return out


@pytest.fixture()
def corpus_settings(settings):
    import_into_db(settings.db_path, list(_sample().values()))
    return settings


# ---------- Unicode normalization & diacritic preservation ----------

def test_normalize_applies_nfc():
    # e + combining acute (two codepoints) must compose to the single
    # NFC codepoint U+00E9.
    decomposed = "e\u0301"  # e + combining acute
    assert len(decomposed) == 2
    assert normalize(decomposed) == "\u00e9"
    assert len(normalize(decomposed)) == 1


def test_normalize_preserves_hebrew_diacritics():
    gen = _sample()["Genesis 1:1"]["source_text"]
    out = normalize(gen)
    assert "ְ" in out  # shewa (niqqud) preserved in the exact key
    assert "ׂ" in out or "ׁ" in out  # shin/sin dot preserved
    assert out == normalize(out)  # idempotent


def test_normalize_nodiac_strips_marks_but_keeps_letters():
    gen = _sample()["Genesis 1:1"]["source_text"]
    nodiac = normalize_nodiac(gen)
    assert "ְ" not in nodiac
    assert nodiac.startswith("בראשית")
    assert normalize_nodiac(gen) != normalize(gen)


def test_tokens_split_and_fold_finals_in_search_key():
    toks = tokens("הַשָּׁמַיִם וְאֵת הָאָרֶץ")
    assert "השמימ" in toks  # final mem folded in the diacritic-insensitive key
    assert all("ְ" not in t for t in toks)


# ---------- Tokenizer ----------

def test_tokenize_source_keeps_diacritics_and_splits_maqqef():
    toks = tokenize_source("עַל־פְּנֵי תְהוֹם׃")
    assert "עַל" in toks and "פְּנֵי" in toks  # maqqef split, marks kept
    assert "׃" in toks  # punctuation is its own token
    assert any("ְ" in t for t in toks)


def test_tokenize_target_keeps_inner_apostrophes():
    toks = tokenize_target("God's Spirit was hovering.")
    assert "God's" in toks
    assert "." in toks


# ---------- Passage segmentation / RTL string handling ----------

def test_split_segments_preserves_order_and_structure():
    text = "שורה ראשונה\n\nשורה שנייה\nשורה שלישית"
    seg = split_segments(text)
    assert [s.source_text for s in seg.segments] == ["שורה ראשונה", "שורה שנייה", "שורה שלישית"]
    assert [s.line_number for s in seg.segments] == [1, 3, 4]
    assert seg.blank_lines == 1 and seg.total_lines == 4
    assert seg.is_multiline is True


def test_reassemble_keeps_segment_order_and_visible_gaps():
    # Reassembly follows the segment order as given (the strings
    # themselves carry their RTL direction in the UI via dir="rtl";
    # the data layer must not reorder, merge, or drop segments), and an
    # untranslated segment stays a visible empty line.
    assert reassemble(["first", "second", "third"]) == "first\nsecond\nthird"
    assert reassemble(["translated", None, "also translated"]) == "translated\n\nalso translated"
    assert reassemble([]) == ""


def test_single_line_is_not_multiline():
    seg = split_segments("only one line")
    assert len(seg.segments) == 1 and seg.is_multiline is False


# ---------- Language suggestion invariant ----------

def test_script_alone_never_classifies():
    out = suggest_language(GEN_1_1)
    assert out["suggestion"] == "uncertain"
    assert out["confidence"] is None
    chosen = suggest_language(GEN_1_1, "biblical_aramaic")
    assert chosen["suggestion"] == "biblical_aramaic"
    assert chosen["basis"] == "user_selection"


# ---------- Morphology: Hebrew and Aramaic analysers stay separate ----------

def test_morphology_aramaic_word_only_in_aramaic_adapter(corpus_settings):
    db = corpus_settings.db_path
    ara = analyze(db, "מַלְכָּא", "biblical_aramaic")
    assert ara["adapter"] == "morphhb_aramaic"
    assert ara["words"][0]["status"] == "found"
    assert all(e["word_language"] == "aramaic" for e in ara["words"][0]["entries"])
    heb = analyze(db, "מַלְכָּא", "biblical_hebrew")
    assert heb["adapter"] == "morphhb_hebrew"
    assert heb["words"][0]["status"] == "not_found"
    assert heb["words"][0]["entries"] == []  # no Hebrew data leaked in, nothing fabricated


def test_morphology_hebrew_word_only_in_hebrew_adapter(corpus_settings):
    db = corpus_settings.db_path
    heb = analyze(db, "אֱלֹהִים", "biblical_hebrew")
    assert heb["words"][0]["status"] == "found"
    assert all(e["word_language"] == "hebrew" for e in heb["words"][0]["entries"])
    ara = analyze(db, "אֱלֹהִים", "biblical_aramaic")
    assert ara["words"][0]["status"] == "not_found"


def test_morphology_unsupported_profile_is_a_validation_error(corpus_settings):
    with pytest.raises(ValidationAppError) as exc:
        analyze(corpus_settings.db_path, "אֱלֹהִים", "classical_syriac")
    assert exc.value.code == "unsupported_language"


# ---------- Passage matching: exact / normalized / variant ----------

def test_retrieval_exact_and_normalized(corpus_settings):
    db = corpus_settings.db_path
    gen = _sample()["Genesis 1:1"]
    exact = retrieval.lookup(db, gen["source_text"], "biblical_hebrew")
    assert exact["match"] is not None and exact["match"]["match_type"] == "exact"
    stripped = normalize_nodiac(gen["source_text"])
    norm = retrieval.lookup(db, stripped, "biblical_hebrew")
    assert norm["match"] is not None and norm["match"]["match_type"] == "normalized"
    assert norm["match"]["reference"] == "Genesis 1:1"


def test_retrieval_variant_is_never_a_match(corpus_settings):
    db = corpus_settings.db_path
    gen = _sample()["Genesis 1:1"]
    variant = gen["source_text"].replace("בָּרָא", "אָמַר", 1)  # one word changed
    out = retrieval.lookup(db, variant, "biblical_hebrew")
    assert out["match"] is None
    if out["variant_candidate"] is not None:
        assert out["variant_candidate"]["match_type"] == "normalized_variant"


def test_retrieval_never_crosses_profiles(corpus_settings):
    db = corpus_settings.db_path
    gen = _sample()["Genesis 1:1"]
    assert retrieval.lookup(db, gen["source_text"], "biblical_aramaic")["match"] is None
    dan = _sample()["Daniel 2:5"]
    assert retrieval.lookup(db, dan["source_text"], "biblical_hebrew")["match"] is None


# ---------- Input validation: every error code ----------

def _gif_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="GIF")
    return buf.getvalue()


def test_validate_empty_upload(settings):
    with pytest.raises(ValidationAppError) as exc:
        validate_and_decode(b"", settings)
    assert exc.value.code == "empty_upload"


def test_validate_upload_too_large(settings):
    small = replace(settings, upload_max_bytes=10)
    with pytest.raises(ValidationAppError) as exc:
        validate_and_decode(png_bytes(), small)
    assert exc.value.code == "upload_too_large"


def test_validate_unsupported_format(settings):
    with pytest.raises(ValidationAppError) as exc:
        validate_and_decode(_gif_bytes(), settings)
    assert exc.value.code == "unsupported_format"


def test_validate_invalid_image(settings):
    with pytest.raises(ValidationAppError) as exc:
        validate_and_decode(b"definitely not an image", settings)
    assert exc.value.code == "invalid_image"


def test_validate_too_many_pixels(settings):
    small = replace(settings, upload_max_pixels=100)
    with pytest.raises(ValidationAppError) as exc:
        validate_and_decode(png_bytes(50, 50), small)
    assert exc.value.code == "image_too_many_pixels"


def test_validate_good_png(settings):
    meta = validate_and_decode(png_bytes(20, 12), settings)
    assert meta["format"] == "PNG" and meta["width"] == 20 and meta["height"] == 12
    assert len(meta["sha256"]) == 64


# ---------- OCR TSV parsing (recorded parser fixture, NOT OCR output) ----------

# A hand-written TSV string in Tesseract's output format, used only to
# test the parser. It is not the output of any OCR run and no accuracy
# claim is made from it.
TSV_FIXTURE = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t800\t200\t-1\t\n"
    "2\t1\t1\t0\t0\t0\t10\t10\t700\t80\t-1\t\n"
    "3\t1\t1\t1\t0\t0\t10\t10\t700\t80\t-1\t\n"
    "4\t1\t1\t1\t1\t0\t10\t10\t700\t40\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t600\t12\t90\t30\t96.5\tבראשית\n"
    "5\t1\t1\t1\t1\t2\t500\t12\t80\t30\t88.0\tברא\n"
    "4\t1\t1\t1\t2\t0\t10\t60\t700\t40\t-1\t\n"
    "5\t1\t1\t1\t2\t1\t580\t62\t95\t30\t42.25\tאלהים\n"
)


def test_parse_tsv_reconstructs_lines_and_confidences():
    parsed = parse_tsv(TSV_FIXTURE)
    assert parsed["text"] == "בראשית ברא\nאלהים"
    assert [w["text"] for w in parsed["words"]] == ["בראשית", "ברא", "אלהים"]
    assert parsed["words"][0]["conf"] == 96.5
    assert parsed["mean_confidence"] == pytest.approx(round((96.5 + 88.0 + 42.25) / 3, 2))


def test_parse_tsv_empty_output():
    parsed = parse_tsv("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n")
    assert parsed["text"] == "" and parsed["words"] == [] and parsed["mean_confidence"] is None


# ---------- Model selection (nothing provisioned -> no selection) ----------

def test_selection_is_none_without_artifacts(settings):
    assert selection.select_engine(settings, "biblical_hebrew") is None
    assert selection.select_engine(settings, "biblical_aramaic") is None


# ---------- Error envelope shape ----------

def test_error_envelope_shape(client):
    r = client.get("/api/jobs/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "detail"}
    assert body["error"]["code"] == "job_not_found"
