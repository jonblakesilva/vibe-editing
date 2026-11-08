"""Caption engine: word-timed ASS subtitles (burned in by FFmpeg/libass) plus
SRT/VTT sidecar files. Captions only use words that were actually spoken; manual
corrections change spelling, never timing."""
from __future__ import annotations

from pathlib import Path

PUNCT_END = (".", "?", "!")


def ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _left_in_sentence(words: list[dict], i: int) -> int:
    n = 0
    for w in words[i:]:
        n += 1
        if w["word"].endswith(PUNCT_END):
            break
    return n


def chunk_words(words: list[dict], *, max_words: int = 6, max_dur: float = 2.8, gap: float = 0.45) -> list[list[dict]]:
    chunks, cur = [], []
    for i, w in enumerate(words):
        paused = cur and w["start"] - cur[-1]["end"] > gap
        # never strand one or two words of a sentence on their own ("battle.")
        tail = _left_in_sentence(words, i) <= 2 and not paused and len(cur) < max_words + 2
        if cur and not tail and (len(cur) >= max_words or paused or w["end"] - cur[0]["start"] > max_dur):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if w["word"].endswith(PUNCT_END):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def _clean(word: str, upper: bool) -> str:
    w = word.strip().replace("{", "(").replace("}", ")").replace("\\", "/")
    w = w.rstrip(",")
    return w.upper() if upper else w


def layout(width: int, height: int, position: str, avoid: list[dict] | None = None) -> dict:
    """Caption anchor that respects platform UI safe zones and avoids faces.

    9:16 platforms put buttons on the right edge and captions/usernames at the bottom
    ~20%, so vertical captions sit around 62-70% of the height. `avoid` holds
    normalized boxes ({x,y,w,h} 0..1) such as detected faces or important screen areas."""
    vertical = height > width
    if position == "auto":
        position = "lower" if vertical else "bottom"
        if avoid:
            for box in avoid:
                face_bottom = box["y"] + box["h"]
                cap_top = 0.60 if vertical else 0.78
                if face_bottom > cap_top and box["y"] < 0.95:
                    position = "top" if box["y"] > 0.45 else ("lower" if vertical else "bottom")
    if position == "top":
        return {"alignment": 8, "margin_v": int(height * (0.14 if vertical else 0.06)), "position": "top"}
    if position == "middle":
        return {"alignment": 5, "margin_v": 0, "position": "middle"}
    if position == "lower" or (vertical and position == "bottom"):
        return {"alignment": 2, "margin_v": int(height * 0.27), "position": "lower"}
    return {"alignment": 2, "margin_v": int(height * 0.07), "position": "bottom"}


def _rounded_rect(x0: float, y0: float, x1: float, y1: float, r: float) -> str:
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    k = r * 0.45  # bezier handle for a smooth quarter circle
    f = lambda v: f"{v:.1f}"
    return (f"m {f(x0 + r)} {f(y0)} l {f(x1 - r)} {f(y0)} "
            f"b {f(x1 - r + k)} {f(y0)} {f(x1)} {f(y0 + r - k)} {f(x1)} {f(y0 + r)} "
            f"l {f(x1)} {f(y1 - r)} b {f(x1)} {f(y1 - r + k)} {f(x1 - r + k)} {f(y1)} {f(x1 - r)} {f(y1)} "
            f"l {f(x0 + r)} {f(y1)} b {f(x0 + r - k)} {f(y1)} {f(x0)} {f(y1 - r + k)} {f(x0)} {f(y1 - r)} "
            f"l {f(x0)} {f(y0 + r)} b {f(x0)} {f(y0 + r - k)} {f(x0 + r - k)} {f(y0)} {f(x0 + r)} {f(y0)}")


def caption_band(width: int, height: int, style: dict) -> dict:
    """Where captions live (pixels), so graphics can keep clear of them."""
    base = min(width, height)
    vertical = height > width
    # phones: larger type, shorter lines
    size = int(style.get("size", 50) * (1.35 if vertical else 1.0) * base / 1080 * float(style.get("size_scale", 1.0)))
    cy = height * (0.735 if vertical else 0.905)
    if style.get("position") == "top":
        cy = height * (0.16 if vertical else 0.1)
    pad_y = size * 0.32
    return {"cy": cy, "size": size, "top": cy - size * 0.62 - pad_y, "bottom": cy + size * 0.62 + pad_y}


def build_premium(words: list[dict], style: dict, *, width: int, height: int, offset: float = 0.0) -> str:
    """Premium captions: one line per phrase on a rounded brand-color panel sized to the
    text, the spoken word lit in the brand highlight color, soft fade. No heavy outlines."""
    from . import fontmetrics
    band = caption_band(width, height, style)
    size, cy = band["size"], band["cy"]
    font = style.get("font", "Outfit Bold")
    spacing = size * 0.01
    primary = ass_color(style.get("primary", "#FFFFFF"))
    hi = ass_color(style.get("highlight") or "#F97316")
    box = style.get("box_color", "#0F1E4A")
    box_a = int(round((1 - float(style.get("box_opacity", 0.82))) * 255))
    pad_x, pad_y, radius = size * 0.55, size * 0.32, size * 0.36
    max_w = width * (0.80 if height > width else 0.62)
    upper = bool(style.get("uppercase"))
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},{primary},{hi},&H00000000,&H00000000,0,0,0,0,100,100,{spacing:.1f},0,1,0,0,5,0,0,0,1",
        f"Style: Box,Arial,10,{ass_color(box, box_a)},{ass_color(box, box_a)},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    # phrases sized by measured width so each fits on one line
    chunks, cur = [], []
    for idx, w in enumerate(words):
        trial = " ".join(_clean(x["word"], upper) for x in cur + [w])
        gap = cur and w["start"] - cur[-1]["end"] > 0.45
        width_now = fontmetrics.text_width(trial, font, size, spacing) if cur else 0
        too_wide = width_now > max_w
        # keep the last one or two words of a sentence with their phrase ("...half the battle.")
        tail = _left_in_sentence(words, idx) <= 2 and width_now <= max_w * 1.1 and not gap
        max_words = int(style.get("max_words", 6)) - (2 if height > width else 0)
        if cur and (gap or too_wide or (len(cur) >= max_words and not tail)):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if w["word"].endswith(PUNCT_END):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    # never leave a lone word: merge a 1-word phrase into the previous one if it fits
    merged: list[list[dict]] = []
    for ch in chunks:
        if merged and len(ch) == 1 and ch[0]["start"] - merged[-1][-1]["end"] < 0.45:
            trial = " ".join(_clean(x["word"], upper) for x in merged[-1] + ch)
            if fontmetrics.text_width(trial, font, size, spacing) <= max_w * 1.15:
                merged[-1] = merged[-1] + ch
                continue
        merged.append(ch)
    body = []
    for ci, ch in enumerate(merged):
        if ci == 0 or merged[ci - 1][-1]["word"].endswith(PUNCT_END):
            first = ch[0]["word"].lstrip()
            ch = [dict(ch[0], word=first[:1].upper() + first[1:])] + ch[1:]
        texts = [_clean(w["word"], upper) for w in ch]
        start = ch[0]["start"] + offset
        nxt = merged[ci + 1][0]["start"] + offset if ci + 1 < len(merged) else None
        end = ch[-1]["end"] + offset + 0.3
        if nxt is not None:
            end = min(end, nxt - 0.01)
        tw = fontmetrics.text_width(" ".join(texts), font, size, spacing)
        cx = width / 2
        x0, x1 = cx - tw / 2 - pad_x, cx + tw / 2 + pad_x
        y0, y1 = cy - size * 0.62 - pad_y, cy + size * 0.62 + pad_y
        box_tags = r"{\fad(90,70)\pos(0,0)\p1}"
        body.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Box,,0,0,0,,{box_tags}"
                    f"{_rounded_rect(x0, y0, x1, y1, radius)}" + r"{\p0}")
        pos = "{\\pos(%.1f,%.1f)}" % (cx, cy)
        for wi, w in enumerate(ch):
            ws = start if wi == 0 else w["start"] + offset
            we = ch[wi + 1]["start"] + offset if wi + 1 < len(ch) else end
            if we - ws < 0.02:
                continue
            parts = ["{\\c%s}%s{\\c%s}" % (hi, tx, primary) if k == wi else tx for k, tx in enumerate(texts)]
            tag = r"{\fad(90,0)}" if wi == 0 else (r"{\fad(0,70)}" if wi == len(ch) - 1 else "")
            body.append(f"Dialogue: 1,{ass_time(ws)},{ass_time(we)},Cap,,0,0,0,,{tag}{pos}" + " ".join(parts))
    return "\n".join(head + body) + "\n"


def build_ass(words: list[dict], style: dict, *, width: int, height: int, avoid: list[dict] | None = None,
              offset: float = 0.0) -> str:
    if style.get("box") == "rounded":
        return build_premium(words, style, width=width, height=height, offset=offset)
    base = height if height < width else width  # scale font with the short side
    scale = base / 1080 * float(style.get("size_scale", 1.0))
    size = int(style.get("size", 64) * scale)
    outline = max(0, int(style.get("outline", 4) * scale))
    shadow = max(0, int(style.get("shadow", 2) * scale))
    lay = layout(width, height, style.get("position", "auto"), avoid)
    primary = ass_color(style.get("primary", "#FFFFFF"))
    hi = ass_color(style["highlight"]) if style.get("highlight") else primary
    border_style = 3 if style.get("box") else 1
    back = ass_color("#000000", 0x60) if style.get("box") else ass_color("#000000", 0x80)
    margin_lr = int(width * (0.10 if height > width else 0.08))
    font = style.get("font", "Montserrat ExtraBold")
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},{primary},{hi},{ass_color('#000000')},{back},-1,0,0,0,100,100,0,0,"
        f"{border_style},{outline},{shadow},{lay['alignment']},{margin_lr},{margin_lr},{lay['margin_v']},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    upper = bool(style.get("uppercase"))
    anim = style.get("animation", "fade")
    events = []
    chunks = chunk_words(words, max_words=int(style.get("max_words", 6)))
    for ci, ch in enumerate(chunks):
        # a sentence whose first word was cut (e.g. "Ah, the second step") still starts with a capital
        if ci == 0 or chunks[ci - 1][-1]["word"].endswith(PUNCT_END):
            first = ch[0]["word"].lstrip()
            ch = [dict(ch[0], word=first[:1].upper() + first[1:])] + ch[1:]
        start = ch[0]["start"] + offset
        nxt = chunks[ci + 1][0]["start"] + offset if ci + 1 < len(chunks) else None
        end = ch[-1]["end"] + offset + 0.25
        if nxt is not None:
            end = min(end, nxt - 0.01)
        texts = [_clean(w["word"], upper) for w in ch]
        lines = int(style.get("lines", 2))
        if anim in ("highlight", "pop"):
            for wi, w in enumerate(ch):
                ws = w["start"] + offset
                we = ch[wi + 1]["start"] + offset if wi + 1 < len(ch) else end
                if we - ws < 0.02:
                    continue
                if anim == "pop" and lines == 1:
                    shown = texts[wi]
                    tag = r"{\fscx80\fscy80\t(0,90,\fscx108\fscy108)\t(90,160,\fscx100\fscy100)}"
                    events.append((ws, we, tag + f"{{\\c{hi}}}" + shown))
                else:
                    parts = []
                    for k, tx in enumerate(texts):
                        if k == wi:
                            parts.append(f"{{\\c{hi}\\fscx108\\fscy108}}{tx}{{\\c{primary}\\fscx100\\fscy100}}")
                        else:
                            parts.append(tx)
                    events.append((ws, we, _wrap(parts, lines)))
        else:
            tag = r"{\fad(80,60)}" if anim == "fade" else ""
            events.append((start, end, tag + _wrap(texts, lines)))
    body = [f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Cap,,0,0,0,,{t}" for s, e, t in events if e > s]
    return "\n".join(head + body) + "\n"


def _wrap(parts: list[str], lines: int) -> str:
    if lines < 2 or len(parts) < 4:
        return " ".join(parts)
    mid = (len(parts) + 1) // 2
    return " ".join(parts[:mid]) + r"\N" + " ".join(parts[mid:])


def sentence_cues(words: list[dict], max_chars: int = 84) -> list[tuple[float, float, str]]:
    cues, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x["word"].strip() for x in cur)
        if w["word"].endswith(PUNCT_END) or len(text) >= max_chars:
            cues.append((cur[0]["start"], cur[-1]["end"], text))
            cur = []
    if cur:
        cues.append((cur[0]["start"], cur[-1]["end"], " ".join(x["word"].strip() for x in cur)))
    return cues


def to_srt(words: list[dict]) -> str:
    out = []
    for i, (s, e, t) in enumerate(sentence_cues(words), 1):
        out.append(f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{_wrap_plain(t)}\n")
    return "\n".join(out)


def to_vtt(words: list[dict]) -> str:
    out = ["WEBVTT", ""]
    for s, e, t in sentence_cues(words):
        out.append(f"{srt_time(s).replace(',', '.')} --> {srt_time(e).replace(',', '.')}\n{_wrap_plain(t)}\n")
    return "\n".join(out)


def _wrap_plain(text: str, width: int = 42) -> str:
    if len(text) <= width:
        return text
    words = text.split()
    mid = len(words) // 2
    return " ".join(words[:mid]) + "\n" + " ".join(words[mid:])


def check_sync(words: list[dict], ass_text: str, tolerance: float = 0.06) -> dict:
    """Every caption event must start at (or within tolerance of) a spoken word start,
    and no event may extend past the next event. Returns a report."""
    starts = sorted(w["start"] for w in words)
    events = []
    for line in ass_text.splitlines():
        if line.startswith("Dialogue:") and ",Box," not in line:
            f = line.split(",", 9)
            events.append((_parse_ass_time(f[1]), _parse_ass_time(f[2])))
    import bisect
    worst = 0.0
    bad = 0
    for s, _e in events:
        i = bisect.bisect_left(starts, s)
        cand = [abs(starts[j] - s) for j in (i - 1, i) if 0 <= j < len(starts)]
        d = min(cand) if cand else 99
        worst = max(worst, d)
        bad += d > tolerance
    overlaps = sum(1 for (s1, e1), (s2, _) in zip(events, events[1:]) if e1 > s2 + 0.011)
    return {"events": len(events), "worst_offset_s": round(worst, 3), "out_of_sync": bad,
            "overlaps": overlaps, "ok": bad == 0 and overlaps == 0}


def _parse_ass_time(s: str) -> float:
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def write_all(words: list[dict], style: dict, out_dir: Path, stem: str, *, width: int, height: int,
              avoid: list[dict] | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ass = build_ass(words, style, width=width, height=height, avoid=avoid)
    paths = {"ass": out_dir / f"{stem}.ass", "srt": out_dir / f"{stem}.srt", "vtt": out_dir / f"{stem}.vtt"}
    paths["ass"].write_text(ass, encoding="utf-8")
    paths["srt"].write_text(to_srt(words), encoding="utf-8")
    paths["vtt"].write_text(to_vtt(words), encoding="utf-8")
    return {k: str(v) for k, v in paths.items()} | {"sync": check_sync(words, ass)}
