"""Render labelled OCR fixture images from real corpus passages.

Ground truth is read from training/datasets/fixtures/sample_passages.jsonl
(real WLC text imported from Open Scriptures morphhb) — no verse text is
typed by hand anywhere in this script. Images are rendered with Pillow
and a Hebrew serif font; when Pillow's RAQM layout engine is available
the text is shaped/directioned as RTL, and that fact (or its absence) is
recorded in ground_truth.json.

Run (from repo root):
  python training/ocr/generate_fixtures.py
  python training/ocr/generate_fixtures.py --font "C:\\Windows\\Fonts\\david.ttf"

Outputs (training/ocr/fixtures/): one PNG per selected passage +
ground_truth.json with provenance, font, and rendering parameters.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, features

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SAMPLE = REPO / "training" / "datasets" / "fixtures" / "sample_passages.jsonl"
OUT_DIR = HERE / "fixtures"
DEFAULT_FONT = "/usr/share/fonts/truetype/noto/NotoSerifHebrew-Regular.ttf"
SELECTED = {"Genesis 1:1": "genesis_1_1_hebrew", "Daniel 2:4": "daniel_2_4_aramaic"}
FONT_SIZE = 44
MARGIN = 60
LINE_SPACING = 1.6
BACKGROUND = 255
FOREGROUND = 0

def load_passages() -> dict[str, dict]:
    out = {}
    for line in SAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            p = json.loads(line)
            out[p["reference"]] = p
    return out

def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split(" ")
    lines, current = [], ""
    for w in words:
        trial = f"{current} {w}".strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current); current = w
    if current:
        lines.append(current)
    return lines

def render(passage: dict, font_path: str, raqm: bool) -> Path:
    name = SELECTED[passage["reference"]]
    font = ImageFont.truetype(font_path, FONT_SIZE)
    probe = Image.new("L", (10, 10), BACKGROUND)
    draw = ImageDraw.Draw(probe)
    max_width = 1100
    lines = wrap(draw, passage["source_text"], font, max_width)
    line_h = int(FONT_SIZE * LINE_SPACING)
    img = Image.new("L", (max_width + 2 * MARGIN, line_h * len(lines) + 2 * MARGIN), BACKGROUND)
    draw = ImageDraw.Draw(img)
    kwargs = {}
    if raqm:
        kwargs = {"direction": "rtl", "language": "he"}
    for i, line in enumerate(lines):
        # With RAQM, anchor at the right edge; without it, Pillow draws in
        # logical order from the left (recorded in ground_truth.json).
        x = img.width - MARGIN if raqm else MARGIN
        anchor = "ra" if raqm else "la"
        draw.text((x, MARGIN + i * line_h), line, font=font, fill=FOREGROUND, anchor=anchor, **kwargs)
    out = OUT_DIR / f"{name}.png"
    img.save(out, dpi=(300, 300))
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", default=DEFAULT_FONT,
                    help="Hebrew font path (Linux default: Noto Serif Hebrew; on Windows pass e.g. C:\\Windows\\Fonts\\david.ttf)")
    args = ap.parse_args()
    if not Path(args.font).exists():
        print(f"Font not found: {args.font}. Pass --font with a Hebrew font path.")
        return 2
    passages = load_passages()
    raqm = bool(features.check("raqm"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    truth = {"font": args.font, "font_size": FONT_SIZE, "raqm": raqm,
             "note": ("Rendered with RAQM RTL shaping." if raqm else
                      "RAQM not available in this Pillow build: glyphs drawn in logical order; "
                      "visual order differs and OCR results must be interpreted with that caveat."),
             "fixtures": []}
    for ref, _name in SELECTED.items():
        p = passages.get(ref)
        if p is None:
            print(f"Passage {ref} not in {SAMPLE}; run the corpus importer sample export first.")
            return 2
        out = render(p, args.font, raqm)
        truth["fixtures"].append({
            "image": out.name, "reference": p["reference"], "language": p["language"],
            "ground_truth": p["source_text"], "source_edition": p["source_edition"],
            "license": p["license"], "provenance": p["provenance"]})
        print(f"wrote {out}")
    (OUT_DIR / "ground_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'ground_truth.json'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
