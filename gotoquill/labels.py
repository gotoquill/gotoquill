"""Normalize PDF labels for signature and date placement."""
import re
import unicodedata

MAX_LABEL_WORDS = 8


def normalize_label(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[\u0000\u0591-\u05c7\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", text)
    text = re.sub(r"[:：]", " ", text)
    text = text.translate(str.maketrans("ךםןףץ׳’״“”", "כמנפצ''\"\"\""))
    text = re.sub(r"(^|[^א-ת])([א-ת](?:\s+[א-ת]){2,})(?=$|[^א-ת])",
                  lambda m: m[1] + re.sub(r"\s", "", m[2]), text)
    return re.sub(r"\s+", " ", text).lower().strip(" \t\n:：._–—*-")


def variants(text: str) -> list[str]:
    s = normalize_label(text)
    return [s, s[::-1], " ".join(w[::-1] for w in s.split(" ")), " ".join(reversed(s.split(" ")))]


def is_id_label(text: str) -> bool:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "").replace("_", " ")
    return any(re.search(
        r"(?:^|[^a-zא-ת])(?:ו?ת[.\s'\"/]*ז|ו?תעודת\s+זהות|ו?מספר\s+זהות|ו?מס['.]?\s+(?:זהות|ת[.\s'\"/]*ז)|"
        r"id(?:\s*(?:number|no))?|national\s+id|passport\s*(?:no|number)|teudat\s+zehut|tz)(?=$|[^a-zא-ת])", s)
        for s in variants(text))


def is_hebrew_date(text: str) -> bool:
    return any(len(s.split()) <= MAX_LABEL_WORDS and re.search(r"(?:^|[\s/:])תאריכ(?:$|[\s/:])", s)
               for s in variants(text))


def is_hebrew_signature(text: str) -> bool:
    if is_hebrew_date(text):
        return False
    return any(len(s.split()) <= MAX_LABEL_WORDS and (
        re.search(r"(?:^|[\s/:])ו?חתימ(?:ה|ת|ות)(?:$|[\s/:])", s)
        or re.search(r"(?:^|[\s/:])חתומ/ה(?:$|[\s/:])", s)
        or (re.search(r"(?:^|[\s/:])(?:חתומ|חתמו|חתמי)(?:$|[\s/:])", s)
            and re.search(r"(?:^|\s)כאנ(?:$|\s)", s))) for s in variants(text))
