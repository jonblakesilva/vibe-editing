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
# "playbook" pace (Nate Herk's measured house reel style): a word ending in "," or one of
# these list markers starts a "natural beat" - a short pause there is left alone rather than
# squeezed to the usual tight gap (see find_pauses's beat_max/beat_keep).
LIST_MARKERS = {"first", "second", "third", "next", "then", "finally", "one", "two", "three", "number"}
NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "dozen", "hundred", "thousand", "million", "billion", "first", "second", "third"}
# Common long function/filler words that shouldn't count as a "charged" punch-in word just
# because they clear the 6-letter bar.
STOPWORDS = {
    "about", "after", "again", "against", "almost", "although", "always", "among", "another", "anyone",
    "anything", "around", "because", "before", "being", "between", "could", "didn't", "does", "doesn't",
    "doing", "during", "either", "enough", "every", "everyone", "everything", "going", "haven't", "having",
    "herself", "himself", "however", "itself", "little", "maybe", "might", "mostly", "myself", "neither",
    "nothing", "obviously", "once", "other", "others", "ourselves", "pretty", "really", "should", "shouldn't",
    "simply", "since", "someone", "something", "sometimes", "still", "such", "suddenly", "themselves", "there",
    "therefore", "these", "they're", "things", "think", "those", "though", "through", "today", "totally",
    "under", "until", "very", "wasn't", "weren't", "whatever", "when", "whether", "which", "while", "whole",
    "whose", "will", "within", "without", "would", "wouldn't", "yourself", "yourselves",
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


def find_pauses(words: list[dict], *, max_pause: float, keep_pause: float,
                beat_max: float | None = None, beat_keep: float | None = None) -> list[dict]:
    """Gaps longer than max_pause are shortened to keep_pause (breathing room stays).

    beat_max/beat_keep (playbook pace only): right after a "natural beat" - a word ending in
    "," or a list marker like "first"/"next" - gaps up to beat_max are left untouched, and
    longer ones are shortened to beat_keep instead of keep_pause."""
    cuts = []
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        is_beat = beat_max is not None and (words[i - 1]["word"].rstrip().endswith(",")
                                            or norm(words[i - 1]["word"]) in LIST_MARKERS)
        if is_beat:
            if gap <= beat_max:
                continue
            keep = beat_keep
        elif gap > max_pause:
            keep = keep_pause
        else:
            continue
        half = keep / 2
        cuts.append({"start": round(words[i - 1]["end"] + half, 3), "end": round(words[i]["start"] - half, 3),
                     "type": "pause", "reason": f"Long pause ({gap:.1f}s) shortened to {keep:.2f}s",
                     "confidence": 0.95})
    return cuts


def find_fillers(words: list[dict], *, aggressive: bool = False, filler_guard: bool = False) -> list[dict]:
    """filler_guard (Nate Herk's rule): a single filler ("um"/"uh") only gets cut cleanly when
    there is silence (>=0.1s) on both sides; otherwise cutting it clips the neighbouring word,
    so it's left in the transcript as a disabled, low-confidence cut for the editor to review."""
    cuts = []
    toks = [norm(w["word"]) for w in words]
    i = 0
    while i < len(words):
        t = toks[i]
        matched = 0
        is_single = t in SINGLE_FILLERS
        if is_single:
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
            text = " ".join(w["word"] for w in words[i:i + matched]).strip(",. ")
            full_text = " ".join(w["word"] for w in words[i:i + matched])
            if is_single and filler_guard:
                prev_gap = words[i]["start"] - words[i - 1]["end"] if i else float("inf")
                next_gap = words[i + 1]["start"] - words[i]["end"] if i + 1 < len(words) else float("inf")
                if prev_gap >= 0.1 and next_gap >= 0.1:
                    cuts.append({"start": s, "end": e, "type": "filler", "reason": f'Filler word "{text}"',
                                 "text": full_text, "confidence": 0.9, "enabled": True})
                else:
                    cuts.append({"start": s, "end": e, "type": "filler",
                                 "reason": f'Filler "{text}" runs into the next word; left in '
                                           "(cutting it would clip words)",
                                 "text": full_text, "confidence": 0.4, "enabled": False})
            else:
                cuts.append({"start": s, "end": e, "type": "filler", "reason": f'Filler word "{text}"',
                             "text": full_text, "confidence": 0.9 if is_single else 0.6})
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


def find_retakes(sents: list[dict], *, reset_pause: float = 2.5, window: float = 120.0,
                 opening: int = 6, min_similarity: float = 0.5) -> list[dict]:
    """Whole-take retries: the speaker stops, resets (a long pause) and starts the same passage
    again, often worded differently ("Hey guys, I'm Jonathan..." / "Hey guys, my name is
    Jonathan..."). A take that opens after a reset pause like a later take does is removed up
    to where that later take starts, so only the last attempt stays."""
    def head(k: int) -> list[str]:  # first words of a take, across sentence breaks ("Hi, everyone. My name...")
        toks: list[str] = []
        for s in sents[k:]:
            toks += s["tokens"]
            if len(toks) >= opening:
                break
        return toks[:opening]

    starts = [k for k, s in enumerate(sents) if k == 0 or s["start"] - sents[k - 1]["end"] >= reset_pause]
    cuts = []
    for n, k in enumerate(starts):
        a = head(k)
        if len(a) < 4:
            continue
        for j in starts[n + 1:]:
            if sents[j]["start"] - sents[k]["start"] > window:
                break
            if _similar(a, head(j)) >= min_similarity:
                cuts.append({"start": sents[k]["start"], "end": sents[j]["start"] - 0.05, "type": "retake",
                             "reason": "Earlier attempt of the same passage - last take kept",
                             "text": " ".join(s["text"] for s in sents[k:j])[:240], "confidence": 0.75})
                break
    return cuts


def find_phrase_retakes(words: list[dict], *, n: int = 6, window: float = 25.0) -> list[dict]:
    """Retries inside one run-on sentence: the same n+ words said again within `window` seconds
    ("or you finished a great project and you never... or you finished a great project and you
    forgot..."). Everything from the first try up to the last try goes; the last try stays."""
    toks = [norm(w["word"]) for w in words]
    cuts, i = [], 0
    while i + n <= len(toks):
        gram = toks[i:i + n]
        if not all(gram):
            i += 1
            continue
        last = None
        for j in range(i + n, len(toks) - n + 1):
            if words[j]["start"] - words[i]["start"] > window:
                break
            if toks[j:j + n] == gram:
                last = j
        if last is None:
            i += 1
            continue
        cuts.append({"start": words[i]["start"], "end": words[last]["start"] - 0.05, "type": "repeat",
                     "reason": "Phrase said again - earlier tries removed, last try kept",
                     "text": " ".join(w["word"] for w in words[i:last])[:240], "confidence": 0.75})
        i = last + n
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


def _is_charged(word: str, keywords: list[str] | None = None) -> bool:
    """A "charged" word for a playbook punch-in: a number, a $ amount, one of the caller's
    keywords, or a word of >=6 letters that isn't a common stopword."""
    raw = word.strip()
    if not raw:
        return False
    if "$" in raw or any(ch.isdigit() for ch in raw):
        return True
    nw = norm(word)
    if not nw:
        return False
    if nw in NUMBER_WORDS:
        return True
    if keywords and nw in {norm(k) for k in keywords}:
        return True
    return len(nw) >= 6 and nw not in STOPWORDS


def first_punch_in(words: list[dict], keywords: list[str] | None = None) -> dict | None:
    """Playbook pace: the first punch-in zoom. The first "charged" word (see _is_charged)
    that starts 0.6-1.0s after the first kept word, or - if none qualify - the word in that
    window starting nearest 0.8s after it."""
    if not words:
        return None
    base = words[0]["start"]
    window = [w for w in words[1:] if 0.6 <= w["start"] - base <= 1.0]
    charged = [w for w in window if _is_charged(w["word"], keywords)]
    if charged:
        chosen = charged[0]
    elif window:
        chosen = min(window, key=lambda w: abs((w["start"] - base) - 0.8))
    else:
        return None
    return {"time": round(chosen["start"], 3), "scale": 1.12, "word": chosen["word"]}


def punch_ins(words: list[dict], duration: float, keywords: list[str] | None = None,
             *, punch_len: float = 1.6) -> list[dict]:
    """Playbook pace: the first punch-in plus later ones on charged sentence-initial words,
    added until 5-15% of `duration` is covered. Each punch lasts about punch_len seconds
    (1.2-2.0s) and none overlap. Returns zoom-shaped dicts: start, end, scale, word, kind."""
    if not words or duration <= 0:
        return []
    first = first_punch_in(words, keywords)
    if not first:
        return []
    base = words[0]["start"]
    end_limit = base + duration
    min_cov, max_cov = 0.05 * duration, 0.15 * duration

    def make(w: dict) -> dict:
        start = w["start"]
        end = min(start + punch_len, end_limit)
        return {"start": round(start, 3), "end": round(end, 3), "scale": 1.12, "word": w["word"], "kind": "punch"}

    first_p = make({"start": first["time"], "word": first["word"]})
    covered = first_p["end"] - first_p["start"]
    if covered <= 0:
        return []
    punches = [first_p]
    for s in sentences(words):
        if covered >= min_cov:
            break
        w = words[s["i0"]]
        if w["start"] <= first_p["start"] + 0.05 or not _is_charged(w["word"], keywords):
            continue
        cand = make(w)
        if cand["end"] - cand["start"] < 0.5:
            continue
        if any(not (cand["end"] <= p["start"] or cand["start"] >= p["end"]) for p in punches):
            continue  # would overlap an existing punch
        if covered + (cand["end"] - cand["start"]) > max_cov:
            continue  # would push total coverage past 15%
        punches.append(cand)
        covered += cand["end"] - cand["start"]
    return punches


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
    takes = {"retake": 0, "restart": 1, "repeat": 2, "false_start": 3}
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
            duration: float | None = None, filler_guard: bool = False) -> dict:
    """duration: length of the media file (may exceed the audio/transcript length)."""
    words = transcript["words"]
    duration = max(duration or 0, transcript["duration"] or (words[-1]["end"] if words else 0))
    sents = sentences(words)
    max_pause, keep_pause = {"relaxed": (1.2, 0.6), "natural": (0.8, 0.4), "tight": (0.5, 0.25),
                             "shorts": (0.35, 0.15), "playbook": (0.2, 0.15)}.get(pace, (0.8, 0.4))
    # Playbook pace keeps the natural-beat exception (see find_pauses's beat_max/beat_keep):
    # a gap right after a comma or list marker ("First,"/"Next"...) up to 0.4s is left alone,
    # longer ones shortened to 0.35s instead of the usual tight keep_pause.
    beat_kwargs = {"beat_max": 0.4, "beat_keep": 0.35} if pace == "playbook" else {}
    cuts = (find_pauses(words, max_pause=max_pause, keep_pause=keep_pause, **beat_kwargs)
            + find_fillers(words, aggressive=aggressive_fillers or pace in ("tight", "shorts", "playbook"),
                          filler_guard=filler_guard)
            + find_restarts_and_repeats(words, sents)
            + find_retakes(sents)
            + find_phrase_retakes(words)
            + find_noise_words(words))
    # Leading/trailing dead air before the first and after the last word. Playbook pace wants
    # speech starting within 0.1s of the clip start instead of the usual 0.2s cushion.
    lead_pad = 0.1 if pace == "playbook" else 0.2
    lead_gate = 0.1 if pace == "playbook" else 0.5
    if words and words[0]["start"] > lead_gate:
        cuts.append({"start": 0.0, "end": words[0]["start"] - lead_pad, "type": "dead_air",
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
