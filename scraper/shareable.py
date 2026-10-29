"""Deterministic randomness and share codes, designed to be ported 1:1 to JavaScript.

PRNG: mulberry32 (32-bit state). Every operation (randint, choice, sample) is implemented here
rather than with Python's `random`, so another language can reproduce the exact same expedition.
Independent streams are derived from (seed, label) with FNV-1a, so changing e.g. the story code
never changes which cards an expedition draws.

Share code: "AEX-" + Crockford base32 of
  byte 0      format version (1)
  byte 1      players-1 (2 bits) | battles-4 (1 bit) | forks-1 (1 bit) | xaxos (1) | friends_foes (1) | campaign (1)
  bytes 2-3   data version (16-bit fingerprint of the expedition DB)
  byte 4      n = number of box-mask bytes
  bytes 5..   box mask, bit i = expedition/box_order.json[i] (all bits set = every box)
  last 4      seed (uint32, big endian)
"""
import json
from pathlib import Path

MASK32 = 0xFFFFFFFF
BOX_ORDER = Path(__file__).resolve().parent.parent / "expedition" / "box_order.json"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
FORMAT_VERSION = 1


def fnv1a(text):
    h = 0x811C9DC5
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & MASK32
    return h


class PRNG:
    """mulberry32. JS equivalent:
        a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
        t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296;
    """

    def __init__(self, seed):
        self.state = seed & MASK32

    @classmethod
    def stream(cls, seed, label):
        return cls(fnv1a(f"{seed}:{label}"))

    def next(self):
        self.state = (self.state + 0x6D2B79F5) & MASK32
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK32
        t = (((t + (((t ^ (t >> 7)) * (t | 61)) & MASK32)) & MASK32) ^ t) & MASK32
        return ((t ^ (t >> 14)) & MASK32) / 4294967296

    def randint(self, n):
        """Uniform integer in [0, n)."""
        return int(self.next() * n)

    def choice(self, items):
        items = list(items)
        return items[self.randint(len(items))]

    def sample(self, items, k):
        """Partial Fisher-Yates on a copy: the first k picks, in pick order."""
        pool = list(items)
        k = min(k, len(pool))
        for i in range(k):
            j = i + self.randint(len(pool) - i)
            pool[i], pool[j] = pool[j], pool[i]
        return pool[:k]


def box_order():
    return json.loads(BOX_ORDER.read_text(encoding="utf-8"))["order"]


def _b32encode(data):
    bits = "".join(f"{b:08b}" for b in data)
    bits += "0" * (-len(bits) % 5)
    return "".join(CROCKFORD[int(bits[i:i + 5], 2)] for i in range(0, len(bits), 5))


def _b32decode(text, nbytes):
    text = text.upper().replace("O", "0").replace("I", "1").replace("L", "1")
    bits = "".join(f"{CROCKFORD.index(c):05b}" for c in text)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, nbytes * 8, 8))


def encode(settings, data_version):
    order = box_order()
    boxes = settings["boxes"] or order
    mask = 0
    for i, b in enumerate(order):
        if b in boxes:
            mask |= 1 << i
    n = (len(order) + 7) // 8
    flags = ((settings["players"] - 1) << 6 | (settings["battles"] - 4) << 5 | (settings["forks"] - 1) << 4
             | settings["xaxos_outcast"] << 3 | settings["friends_foes"] << 2 | settings["campaign_mechanics"] << 1)
    data = (bytes([FORMAT_VERSION, flags]) + (data_version & 0xFFFF).to_bytes(2, "big") + bytes([n])
            + mask.to_bytes(n, "little") + (settings["seed"] & MASK32).to_bytes(4, "big"))
    code = _b32encode(data)
    return "AEX-" + "-".join(code[i:i + 5] for i in range(0, len(code), 5))


def decode(code):
    text = code.upper().removeprefix("AEX-").replace("-", "").strip()
    head = _b32decode(text[:8], 5)
    if head[0] != FORMAT_VERSION:
        raise ValueError(f"unsupported share code version {head[0]}")
    n = head[4]
    data = _b32decode(text, 5 + n + 4)
    flags = data[1]
    mask = int.from_bytes(data[5:5 + n], "little")
    order = box_order()
    boxes = [b for i, b in enumerate(order) if mask >> i & 1]
    settings = {
        "players": (flags >> 6 & 3) + 1, "battles": (flags >> 5 & 1) + 4, "forks": (flags >> 4 & 1) + 1,
        "xaxos_outcast": bool(flags >> 3 & 1), "friends_foes": bool(flags >> 2 & 1),
        "campaign_mechanics": bool(flags >> 1 & 1),
        "boxes": [] if len(boxes) == len(order) else boxes,
        "seed": int.from_bytes(data[5 + n:9 + n], "big"),
    }
    return settings, int.from_bytes(data[2:4], "big")
