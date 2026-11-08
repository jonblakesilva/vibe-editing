"""Editing intelligence: find mistakes, pauses, hooks and chapters in a word-level
transcript. Deterministic and offline, so it works without any paid API. The
active Claude Code session (or an optional LLM provider) reviews and refines the
resulting plan; this module never invents or rewrites spoken words."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# Filler lists follow the original kit's Speaker SOP (skills/edit/scripts/detect_fillers.py).
SINGLE_FILLERS = {"um", "uh", "uhm", "umm", "uhh", "erm", "er", "ah", "ahh", "hmm", "mm"}
SOFT_FILLERS = {"like", "so", "okay", "ok", "right", "basically", "actually", "literally"}
PHRASE_FILLERS = [("you", "know"), ("i", "mean"), ("kind", "of"), ("sort", "of")]
RESTART_PHRASES = [
    "let me start that again", "let me start again", "let me start over", "start that again",
    "let me try that again", "let me redo that", "let me say that again", "scratch that",
    "start over", "take two", "one more time", "let me rephrase", "sorry let me", "i'll start again",
    "cut that", "redo that",
]
APOLOGY_WORDS = {"sorry", "oops", "wait", "no", "okay", "ok", "so", "um", "uh", "actually", "hold", "on"}
LEAD_WORDS = {"so", "and", "now", "okay", "ok", "um", "uh", "well", "alright", "right", "but"}
CTA_PHRASES = ["link below", "link in the description", "book a call", "book a free", "subscribe",
               "sign up", "download", "click the link", "dm me", "comment below", "join", "get started",
               "schedule", "free call", "free checklist", "grab the"]
HOOK_WORDS = {"secret", "mistake", "mistakes", "never", "stop", "lose", "losing", "why", "how", "biggest",
              "most", "only", "nobody", "everyone", "truth", "free", "fastest", "easiest", "without",
              "half", "double", "triple", "proven", "system", "exactly", "wrong", "fail", "money"}
CHAPTER_MARKERS = [r"\b(first|second|third|fourth|fifth|next|final|last) (step|thing|tip|mistake|reason|part)\b",
                   r"\bstep (one|two|three|four|five|\d+)\b", r"\bnumber (one|two|three|four|five|\d+)\b",
                   r"\blet'?s (talk about|look at|move on|get into|dive into)\b", r"\bmoving on\b",
                   r"\bin conclusion\b", r"\bto wrap (this )?up\b", r"\bquestion is\b"]
VIDEO_TYPE_KEYWORDS = {
    "tutorial": ["click", "screen", "settings", "open", "button", "menu", "tab", "type", "select", "drag",
                 "install", "dashboard", "step", "navigate", "here you can see"],
    "sales": ["offer", "price", "guarantee", "results", "clients", "book a call", "investment", "bonus",
              "limited", "testimonial", "revenue", "roi", "pay"],
    "promo": ["introducing", "launch", "new", "available now", "announcing", "coming soon"],
    "interview": ["question", "tell us", "what do you think", "your experience", "welcome to the show"],
}

_PUNCT = re.compile(r"[^\w']+")


def norm(word: str) -> str:
    return _PUNCT.sub("", word.lower())


def sentences(words: list[dict], *, gap: float = 0.7) -> list[dict]:
    """Group words into sentences using punctuation and pauses."""
    out, cur = [], []
    for i, w in enumerate(words):
        if cur and (w["start"] - words[i - 1]["end"] > gap):
            out.append(cur)
            cur = []
        cur.append(i)
        if w["word"].rstrip().endswith((".", "?", "!")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    result = []
    for idx in out:
        text = " ".join(words[i]["word"] for i in idx).strip()
        result.append({"i0": idx[0], "i1": idx[-1], "start": words[idx[0]]["start"],
                       "end": words[idx[-1]]["end"], "text": text,
                       "tokens": [norm(words[i]["word"]) for i in idx if norm(words[i]["word"])]})
    return result


def find_pauses(words: list[dict], *, max_pause: float, keep_pause: float) -> list[dict]:
    """Gaps longer than max_pause are shortened to keep_pause (breathing room stays)."""
    cuts = []
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap > max_pause:
            half = keep_pause / 2
            cuts.append({"start": round(words[i - 1]["end"] + half, 3), "end": round(words[i]["start"] - half, 3),
                         "type": "pause", "reason": f"Long pause ({gap:.1f}s) shortened to {keep_pause:.2f}s",
                         "confidence": 0.95})
    return cuts


def find_fillers(words: list[dict], *, aggressive: bool = False) -> list[dict]:
    cuts = []
    toks = [norm(w["word"]) for w in words]
    i = 0
    while i < len(words):
        t = toks[i]
        matched = 0
        if t in SINGLE_FILLERS:
            matched = 1
        else:
            for ph in PHRASE_FILLERS:
                if tuple(toks[i:i + len(ph)]) == ph and aggressive:
                    matched = len(ph)
                    break
            if not matched and aggressive and t in SOFT_FILLERS:
                prev_gap = words[i]["start"] - words[i - 1]["end"] if i else 1
                next_gap = words[i + 1]["start"] - words[i]["end"] if i + 1 < len(words) else 1
                if prev_gap > 0.25 and next_gap > 0.2:  # isolated hesitation, not grammar
                    matched = 1
        if matched:
            s, e = words[i]["start"], words[i + matched - 1]["end"]
            cuts.append({"start": s, "end": e, "type": "filler",
                         "reason": f'Filler word "{" ".join(w["word"] for w in words[i:i + matched]).strip(",. ")}"',
                         "text": " ".join(w["word"] for w in words[i:i + matched]), "confidence": 0.9 if matched and t in SINGLE_FILLERS else 0.6})
            i += matched
        else:
            i += 1
    return cuts


def _similar(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def find_restarts_and_repeats(words: list[dict], sents: list[dict]) -> list[dict]:
    """Bad takes: explicit restart phrases, false starts and repeated sentences.
    The LAST take is kept (speakers usually nail it on the retry)."""
    cuts = []
    text_lower = [s["text"].lower() for s in sents]
    for k, s in enumerate(sents):
        low = " ".join(s["tokens"])
        # 1) Explicit restart phrase: remove the abandoned sentence(s) and the apology itself.
        for ph in RESTART_PHRASES:
            if ph in low:
                start_k = k
                pos = low.find(ph)
                before = [t for t in low[:pos].split() if t not in APOLOGY_WORDS]
                # Apology-only lead-in ("Sorry, let me start again") -> the previous sentence was the bad take.
                if not before and k > 0:
                    start_k = k - 1  # apology sentence follows the abandoned one
                cuts.append({"start": sents[start_k]["start"], "end": s["end"], "type": "restart",
                             "reason": f'Restart ("{ph}") - abandoned take removed',
                             "text": " ".join(sents[j]["text"] for j in range(start_k, k + 1)),
                             "confidence": 0.85})
                break
    for k, s in enumerate(sents):
        for j in range(k + 1, min(k + 4, len(sents))):
            a, b = _strip_lead(s["tokens"]), _strip_lead(sents[j]["tokens"])
            if len(a) < 3:
                continue
            ratio = _similar(a, b)
            prefix = len(a) <= len(b) and b[:max(2, len(a) - 1)] == a[:max(2, len(a) - 1)]
            between = sum(len(sents[m]["tokens"]) for m in range(k + 1, j))
            if (ratio >= 0.8 or (prefix and len(a) < len(b))) and between <= 12:
                kind = "repeat" if ratio >= 0.8 else "false_start"
                cuts.append({"start": s["start"], "end": sents[j]["start"] - 0.05, "type": kind,
                             "reason": "Repeated sentence - earlier take removed, best (last) take kept"
                             if kind == "repeat" else "False start - sentence restarted",
                             "text": s["text"], "confidence": 0.8 if kind == "repeat" else 0.7})
                break
    _ = text_lower
    return cuts


def _strip_lead(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens) and tokens[i] in LEAD_WORDS:
        i += 1
    return tokens[i:]


def find_noise_words(words: list[dict]) -> list[dict]:
    """Speech recognisers sometimes 'hear' a word inside long silence. A low-confidence
    word isolated by long gaps on both sides is flagged (enabled only if very unlikely)."""
    cuts = []
    for i, w in enumerate(words):
        prev_gap = w["start"] - words[i - 1]["end"] if i else w["start"]
        next_gap = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else 9
        prob = w.get("prob", 1)
        if norm(w["word"]) in SINGLE_FILLERS:
            continue  # handled as a filler
        if (prev_gap > 1.0 and next_gap > 0.6 and prob < 0.6) or (max(prev_gap, next_gap) > 1.0 and prob < 0.2):
            cuts.append({"start": w["start"] - 0.05, "end": w["end"] + 0.05, "type": "noise",
                         "reason": f'Probably not speech: "{w["word"]}" (confidence {w.get("prob", 0):.0%})',
                         "text": w["word"], "confidence": 0.75 if w.get("prob", 1) < 0.35 else 0.55})
    return cuts


def score_hook(sent: dict, position: float) -> float:
    toks = sent["tokens"]
    n = len(toks)
    if n < 5:
        return 0.0
    score = 0.0
    score += min(3.0, sum(1 for t in toks if t in HOOK_WORDS) * 1.0)
    score += 1.5 if any(t.isdigit() or t in {"one", "two", "three", "five", "ten", "half"} for t in toks) else 0
    score += 1.0 if "you" in toks or "your" in toks else 0
    score += 1.0 if sent["text"].strip().endswith("?") else 0
    score += 1.0 if 8 <= n <= 25 else (-1.0 if n > 40 else 0)
    score += 1.0 * (1 - position)  # earlier is slightly better for an opening hook
    return round(score, 2)


def find_hooks(sents: list[dict], duration: float, top: int = 3) -> list[dict]:
    scored = [{"start": s["start"], "end": s["end"], "text": s["text"],
               "score": score_hook(s, s["start"] / max(duration, 1))} for s in sents]
    scored = [s for s in scored if s["score"] > 0]
    scored.sort(key=lambda s: -s["score"])
    return scored[:top]


def _inside(s: dict, cuts: list[dict]) -> bool:
    mid = (s["start"] + s["end"]) / 2
    return any(c.get("enabled", True) and c["start"] <= mid <= c["end"] for c in cuts)


def find_chapters(sents: list[dict], duration: float, *, min_gap: float | None = None,
                  cuts: list[dict] | None = None) -> list[dict]:
    """Chapters on SOURCE times (the plan maps them to the edited timeline). Sentences that
    are being cut never start a chapter. YouTube needs >=3 chapters, first at 0:00, >=10 s each."""
    min_gap = min_gap or max(10.0, duration / 12)
    chapters = [{"start": 0.0, "title": "Introduction"}]
    for s in sents:
        if cuts and _inside(s, cuts):
            continue
        low = s["text"].lower()
        if any(re.search(p, low) for p in CHAPTER_MARKERS) and s["start"] - chapters[-1]["start"] >= min_gap:
            title = _chapter_title(s["text"])
            chapters.append({"start": round(s["start"], 2), "title": title})
    if duration - chapters[-1]["start"] < 10 and len(chapters) > 1:
        chapters.pop()
    return chapters


def _chapter_title(text: str) -> str:
    clean = re.sub(r"[^\w\s']", "", text)
    # "The first step is to answer every lead" -> "Answer every lead"
    clean = re.sub(r"^(?:(?:so|and|now|okay|uh|um)\s+)*(?:the\s+)?(?:\w+\s+)?(?:step|thing|tip|mistake|reason|part)"
                   r"(?:\s+\w+)?\s+(?:is\s+)?(?:to\s+)?", "", clean, flags=re.I) or clean
    clean = re.sub(r"^(?:let'?s\s+(?:talk about|look at|get into|dive into)\s+)", "", clean, flags=re.I)
    words = clean.split()
    title = " ".join(words[:7])
    return title[:1].upper() + title[1:] if title else "Section"


def find_cta(sents: list[dict]) -> list[dict]:
    return [{"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in sents if any(p in s["text"].lower() for p in CTA_PHRASES)]


def classify(words: list[dict]) -> dict:
    text = " " + " ".join(norm(w["word"]) for w in words) + " "
    scores = {k: sum(text.count(f" {kw} ") for kw in kws) for k, kws in VIDEO_TYPE_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    vtype = best if scores[best] >= 3 else "talking_head"
    return {"type": vtype, "scores": scores}


def merge_cuts(cuts: list[dict], duration: float) -> list[dict]:
    """Sort, clamp and drop zero-length cuts. Overlapping cuts stay as separate,
    reviewable items; the renderer unions them."""
    out = []
    for c in sorted(cuts, key=lambda c: (c["start"], c["end"])):
        c["start"], c["end"] = round(max(0.0, c["start"]), 3), round(min(duration, c["end"]), 3)
        if c["end"] - c["start"] >= 0.05:
            out.append(c)
    # One reviewable item per problem: overlapping bad-take cuts merge into one
    # (restart > repeat > false start), and pauses/fillers inside a bad take disappear.
    takes = {"restart": 0, "repeat": 1, "false_start": 2}
    merged: list[dict] = []
    for c in out:
        if c["type"] in takes and merged and merged[-1]["type"] in takes and c["start"] <= merged[-1]["end"]:
            m = merged[-1]
            if takes[c["type"]] < takes[m["type"]]:
                m["type"], m["reason"], m["text"] = c["type"], c["reason"], c.get("text", m.get("text"))
            m["end"] = max(m["end"], c["end"])
            m["confidence"] = max(m.get("confidence", 0), c.get("confidence", 0))
            continue
        merged.append(c)
    bad = [c for c in merged if c["type"] in takes]
    return [c for c in merged if c["type"] in takes or not any(
        d["start"] <= c["start"] and c["end"] <= d["end"] for d in bad)]


def analyze(transcript: dict, *, pace: str = "natural", aggressive_fillers: bool = False,
            duration: float | None = None) -> dict:
    """duration: length of the media file (may exceed the audio/transcript length)."""
    words = transcript["words"]
    duration = max(duration or 0, transcript["duration"] or (words[-1]["end"] if words else 0))
    sents = sentences(words)
    max_pause, keep_pause = {"relaxed": (1.2, 0.6), "natural": (0.8, 0.4), "tight": (0.5, 0.25),
                             "shorts": (0.35, 0.15)}.get(pace, (0.8, 0.4))
    cuts = (find_pauses(words, max_pause=max_pause, keep_pause=keep_pause)
            + find_fillers(words, aggressive=aggressive_fillers or pace in ("tight", "shorts"))
            + find_restarts_and_repeats(words, sents)
            + find_noise_words(words))
    # Leading/trailing dead air before the first and after the last word.
    if words and words[0]["start"] > 0.5:
        cuts.append({"start": 0.0, "end": words[0]["start"] - 0.2, "type": "dead_air",
                     "reason": "Silence before first word", "confidence": 0.95})
    if words and duration - words[-1]["end"] > 0.8:
        cuts.append({"start": words[-1]["end"] + 0.4, "end": duration, "type": "dead_air",
                     "reason": "Silence after last word", "confidence": 0.95})
    cuts = merge_cuts(cuts, duration)
    for n, c in enumerate(cuts):
        c["id"] = f"c{n + 1}"
        c["enabled"] = c.get("confidence", 1) >= 0.6
    return {
        "duration": duration,
        "classification": classify(words),
        "sentences": [{k: v for k, v in s.items() if k != "tokens"} for s in sents],
        "cuts": cuts,
        "hooks": find_hooks(sents, duration),
        "chapters": find_chapters(sents, duration, cuts=cuts),
        "cta": find_cta(sents),
        "pace": pace,
    }
