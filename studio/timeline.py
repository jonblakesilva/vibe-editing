"""Keep-segments and source->edited time mapping."""
from __future__ import annotations

from bisect import bisect_right


def snap(t: float, fps: float) -> float:
    """Round to a frame boundary so audio and video segments have identical lengths
    (prevents drift accumulating over hundreds of cuts)."""
    return round(round(t * fps) / fps, 6)


def keep_segments(duration: float, cuts: list[dict], *, fps: float = 30.0, min_keep: float = 0.25,
                  extra: list[tuple[float, float]] | None = None) -> list[tuple[float, float]]:
    """Complement of the union of enabled cuts. Tiny leftover slivers are dropped."""
    spans = sorted((c["start"], c["end"]) for c in cuts if c.get("enabled", True))
    spans += list(extra or [])
    spans.sort()
    merged: list[list[float]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1] + 0.02:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    keeps, t = [], 0.0
    for s, e in merged:
        if s - t >= min_keep:
            keeps.append((t, s))
        t = max(t, e)
    if duration - t >= min_keep:
        keeps.append((t, duration))
    out = []
    for s, e in keeps:
        s2, e2 = snap(s, fps), snap(e, fps)
        if e2 - s2 >= 1 / fps:
            out.append((s2, e2))
    return out


SILENCE_CUT_TYPES = {"pause", "dead_air"}


def pad_cut_starts(cuts: list[dict], pad: float) -> list[dict]:
    """Delay the start of each non-silence cut by `pad` seconds. Transcripts end words
    40-80ms before the consonant actually dies, so cutting exactly at the transcript's
    word boundary clips the tail of the kept word; nudging the cut's start later lets that
    decay survive. Pause/dead_air cuts already start in silence, so they're left alone.
    The padded start never leaves the cut's own [start, end] span (still inside the
    silence/removed region), and a cut shrunk below 0.05s by the pad is left unpadded."""
    out = []
    for c in cuts:
        if c.get("type") in SILENCE_CUT_TYPES:
            out.append(c)
            continue
        new_start = round(c["start"] + pad, 6)
        if c["end"] - new_start >= 0.05:
            out.append({**c, "start": new_start})
        else:
            out.append(c)
    return out


class Timeline:
    """Maps times in the original recording to times in the edited video."""

    def __init__(self, segments: list[tuple[float, float]]):
        self.segments = segments
        self.starts = [s for s, _ in segments]
        self.offsets = []
        acc = 0.0
        for s, e in segments:
            self.offsets.append(acc)
            acc += e - s
        self.duration = acc

    def to_edit(self, t: float) -> float | None:
        """Edited-video time for a source time, or None if that moment was cut."""
        i = bisect_right(self.starts, t) - 1
        if i < 0:
            return None
        s, e = self.segments[i]
        if t > e + 1e-6:
            return None
        return self.offsets[i] + (t - s)

    def to_edit_nearest(self, t: float) -> float:
        """Like to_edit, but a cut moment maps to the next kept moment."""
        v = self.to_edit(t)
        if v is not None:
            return v
        i = bisect_right(self.starts, t)
        if i >= len(self.segments):
            return self.duration
        return self.offsets[i]

    def to_source(self, t: float) -> float:
        i = max(0, bisect_right(self.offsets, t) - 1)
        s, _ = self.segments[i]
        return s + (t - self.offsets[i])

    def span_to_edit(self, start: float, end: float) -> tuple[float, float] | None:
        a, b = self.to_edit_nearest(start), self.to_edit_nearest(end)
        if b - a < 0.05:
            return None
        return a, b

    def map_words(self, words: list[dict]) -> list[dict]:
        """Words fully inside kept segments, retimed to the edited video."""
        out = []
        for i, w in enumerate(words):
            mid = (w["start"] + w["end"]) / 2
            if self.to_edit(mid) is None:
                continue
            s = self.to_edit(w["start"])
            e = self.to_edit(w["end"])
            if s is None:
                s = self.to_edit_nearest(w["start"])
            if e is None:
                # word end falls in a cut: clip to the end of its segment
                j = bisect_right(self.starts, mid) - 1
                e = self.offsets[j] + (self.segments[j][1] - self.segments[j][0])
            out.append({**w, "start": round(s, 3), "end": round(max(e, s + 0.04), 3), "src_index": i})
        return out
