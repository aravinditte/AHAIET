from __future__ import annotations
# Part 1 interface stub: no model/corpus is provisioned yet, so callers must
# treat this module as unavailable. It intentionally returns no fabricated data.
STATUS = "not_provisioned"
REASON = "retrieval analysis requires provisioned linguistic artifacts; none exist in Part 1. See docs/BUILD_STATE.md."
def status() -> dict:
    return {"status": STATUS, "reason": REASON}
