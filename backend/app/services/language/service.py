from __future__ import annotations
SUPPORTED = ["biblical_hebrew", "biblical_aramaic"]
FUTURE = ["old_epigraphic_hebrew", "paleo_hebrew", "qumran_hebrew", "old_aramaic", "imperial_aramaic",
          "jewish_palestinian_aramaic", "jewish_babylonian_aramaic", "classical_syriac"]
def suggest_language(text: str, selected: str | None = None) -> dict:
    # INVARIANT: Hebrew script alone never identifies the language.
    # Biblical Aramaic is written in Hebrew characters, so script detection
    # cannot distinguish it from Biblical Hebrew. Without corpus/morphology
    # evidence (not provisioned in Part 1) we must return 'uncertain'.
    if selected in SUPPORTED:
        return {"suggestion": selected, "confidence": None, "basis": "user_selection",
                "warnings": []}
    return {"suggestion": "uncertain", "confidence": None, "basis": "script_only_insufficient",
            "warnings": ["Script alone cannot distinguish Biblical Hebrew from Biblical Aramaic (both use Hebrew characters). Please select a language profile; no automatic classification was made."]}
