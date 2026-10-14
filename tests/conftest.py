import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def words(*items):
    """[("hello", 0.0, 0.4), ...] -> Whisper-style word dicts (leading space like faster-whisper)."""
    return [{"w": " " + w, "s": s, "e": e, "p": 0.9} for w, s, e in items]
