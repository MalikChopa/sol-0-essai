"""`rover restore`: republish a named checkpoint after validation (SPEC 6.12, 10 case 18)."""
from __future__ import annotations

import time

from rover.config import Params
from rover.core.types import JournalEntry
from rover.pipeline.sol import SolResult, _status
from rover.stages import progress as stage_progress
from rover.state import LoadResult, validate


def restore_result(lr: LoadResult, now_utc: str, prev_images: dict, images_sol: int | None, params: Params) -> SolResult:
    """The restored core, `epoch` already + 1 by `state.load_checkpoint`; `sol` stays that of the checkpoint (no sol is played).
    The images are those of `_in` (a restoration draws nothing), flagged in `status.json.det.warnings`."""
    t0 = time.monotonic()
    s = lr.state
    h = s["health"]
    h.update(attempts=0, incident=None, passive_streak=0)
    s["last_run_utc"] = now_utc
    s["pending_tags"] = []
    name = h["restored_from"]
    fr = f"Restauration manuelle : retour au point {name} (époque {s['epoch']})."
    en = f"Manual restore: back to checkpoint {name} (epoch {s['epoch']})."
    e = JournalEntry(epoch=s["epoch"], sol=s["sol"], utc=now_utc, fr=fr, en=en)
    s["journal_tail"] = (s["journal_tail"] + [{"epoch": e.epoch, "sol": e.sol, "utc": now_utc, "fr": fr, "en": en}])[-30:]
    probs = validate(s)
    if probs:
        raise ValueError("restored state invalid: " + "; ".join(probs[:3]))
    images = dict(prev_images)
    warnings = ["manual_restore"]
    if images:
        warnings.append("images_from_sol_%s" % (images_sol if images_sol is not None else "unknown"))
    prog = stage_progress(s["stage"], s["metrics"], params)
    status = _status(s, prog, {}, now_utc, warnings, {"total": round(time.monotonic() - t0, 3)},
                     len(images.get("console.gif", b"")), None, params)
    return SolResult(state=s, explored=lr.explored, trace=None, facts={"restored_from": name, "restore_cause": "manual"},
                     journal=[e], tags=[], images=images, status=status)
