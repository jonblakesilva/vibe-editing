"""Long-form -> Shorts: find stand-alone moments and score them editorially.

Scores (0-10) are editorial judgements, NOT performance predictions:
hook, value (educational), clarity, relevance, standalone, retention, cta.
Clips always begin and end on sentence boundaries and only contain spoken words."""
from __future__ import annotations

from . import analyze as an

WEIGHTS = {"hook": 0.24, "value": 0.18, "clarity": 0.12, "relevance": 0.12, "standalone": 0.16,
           "retention": 0.12, "cta": 0.06}
DEPENDENT_STARTS = {"and", "but", "so", "because", "that", "it", "this", "these", "those", "he", "she",
                    "they", "which", "also", "then", "or", "plus", "like", "anyway", "yeah"}
VALUE_WORDS = {"step", "steps", "how", "tip", "because", "should", "mistake", "mistakes", "why", "secret",
               "exactly", "framework", "system", "process", "rule", "always", "never", "instead", "first",
               "second", "third", "result", "results", "example", "means", "learn"}


def _clip10(x: float) -> float:
    return round(max(0.0, min(10.0, x)), 1)


def score_window(sents: list[dict], words: list[dict], topics: list[str], cuts: list[dict]) -> dict:
    first, last = sents[0], sents[-1]
    toks = [t for s in sents for t in s["tokens"]]
    n = max(1, len(toks))
    dur = last["end"] - first["start"]
    w_in = [w for w in words if first["start"] <= w["start"] <= last["end"]]
    probs = [w.get("prob", 1.0) for w in w_in] or [1.0]
    fillers = sum(1 for t in toks if t in an.SINGLE_FILLERS)
    cut_secs = sum(max(0, min(c["end"], last["end"]) - max(c["start"], first["start"]))
                   for c in cuts if c.get("enabled", True) and c["type"] in ("retake", "restart", "repeat", "false_start"))
    hook = an.score_hook(first, 0.0) * 1.4
    if first["tokens"] and first["tokens"][0] in DEPENDENT_STARTS:
        hook -= 3
    value = sum(1 for t in toks if t in VALUE_WORDS) / n * 60 + (2 if any(t.isdigit() for t in toks) else 0)
    clarity = 10 * (sum(probs) / len(probs)) - fillers * 0.8 - cut_secs * 0.5
    topic_set = {w for t in topics for w in an.norm(t).split()}
    relevance = (sum(1 for t in toks if t in topic_set) / n * 80 if topic_set else 4) \
        + sum(1 for t in toks if t in ("you", "your")) / n * 40
    standalone = 10.0
    if first["tokens"] and first["tokens"][0] in DEPENDENT_STARTS:
        standalone -= 4
    if any(t in ("earlier", "before", "mentioned", "said") for t in first["tokens"]):
        standalone -= 3
    if not last["text"].rstrip().endswith((".", "!", "?")):
        standalone -= 2
    if len(sents) < 2:
        standalone -= 2
    wps = n / max(dur, 1)
    gaps = sum(1 for a, b in zip(w_in, w_in[1:]) if b["start"] - a["end"] > 1.0)
    retention = 10 - abs(wps - 2.9) * 3 - gaps * 0.7 + (1.5 if first["text"].strip().endswith("?") else 0)
    cta = 8 if any(p in " ".join(s["text"].lower() for s in sents) for p in an.CTA_PHRASES) else (
        6 if last["text"].rstrip().endswith("!") else 3)
    scores = {"hook": _clip10(hook), "value": _clip10(value), "clarity": _clip10(clarity),
              "relevance": _clip10(relevance), "standalone": _clip10(standalone),
              "retention": _clip10(retention), "cta": _clip10(cta)}
    total = round(sum(scores[k] * w for k, w in WEIGHTS.items()), 2)
    return {"scores": scores, "total": total}


def find_clips(transcript: dict, analysis: dict, *, count: int = 5, min_len: float = 20.0,
               max_len: float = 60.0, topics: list[str] | None = None) -> list[dict]:
    words = transcript["words"]
    cuts = analysis["cuts"]
    sents = [dict(s, tokens=[an.norm(t) for t in s["text"].split() if an.norm(t)]) for s in analysis["sentences"]]
    # never start or end on a take that is being removed
    usable = [s for s in sents if not an._inside(s, [c for c in cuts if c["type"] in
                                                     ("retake", "restart", "repeat", "false_start", "noise")])]
    cands = []
    for i in range(len(usable)):
        for j in range(i, len(usable)):
            dur = usable[j]["end"] - usable[i]["start"]
            removed = sum(max(0, min(c["end"], usable[j]["end"]) - max(c["start"], usable[i]["start"]))
                          for c in cuts if c.get("enabled", True))
            edited = dur - removed
            if edited > max_len:
                break
            if edited < min_len:
                continue
            sc = score_window(usable[i:j + 1], words, topics or [], cuts)
            cands.append({"start": round(max(0, usable[i]["start"] - 0.15), 3), "end": round(usable[j]["end"] + 0.3, 3),
                          "est_duration": round(edited, 1), "hook": usable[i]["text"],
                          "text": " ".join(s["text"] for s in usable[i:j + 1]), **sc})
    if not cands and usable:
        # recording shorter than min_len: offer the whole thing as one clip
        sc = score_window(usable, words, topics or [], cuts)
        cands.append({"start": usable[0]["start"], "end": usable[-1]["end"] + 0.3,
                      "est_duration": round(usable[-1]["end"] - usable[0]["start"], 1),
                      "hook": usable[0]["text"], "text": " ".join(s["text"] for s in usable), **sc})
    cands.sort(key=lambda c: -c["total"])
    chosen: list[dict] = []
    for c in cands:
        if all(c["end"] <= o["start"] or c["start"] >= o["end"] for o in chosen):
            chosen.append(c)
        if len(chosen) >= count:
            break
    for n, c in enumerate(chosen, 1):
        c["id"] = f"s{n}"
        c["enabled"] = True
        c["title"] = suggest_title(c["hook"])
    return chosen


def suggest_title(hook: str) -> str:
    words = hook.replace(",", "").split()
    t = " ".join(words[:9]).rstrip(".!?")
    return t[:1].upper() + t[1:]
