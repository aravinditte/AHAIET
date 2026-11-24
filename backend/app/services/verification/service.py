from __future__ import annotations
# Verification of retrieval results: a match may be presented as a
# verified reference only if it carries a passage identity, both edition
# names, a licence, and provenance. Variant candidates never verify.
def verify_reference(match: dict | None) -> dict:
    if not match:
        return {"verified": False, "checks": {"match_present": False}}
    checks = {
        "match_present": True,
        "match_type_verified": match.get("match_type") in ("exact", "normalized"),
        "has_reference": bool(match.get("reference")),
        "has_source_edition": bool(match.get("source_edition")),
        "has_translation_edition": bool(match.get("translation_edition")),
        "has_license": bool(match.get("license")),
        "has_provenance": bool(match.get("provenance")),
        "has_english_text": bool(match.get("english_text")),
    }
    return {"verified": all(checks.values()), "checks": checks}

def status() -> dict:
    return {"status": "available",
            "reason": "Reference verification is rule-based over retrieval provenance fields (no model required)."}
