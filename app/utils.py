import html
import re


# Unicode → ASCII-friendly replacements
_UNICODE_MAP = str.maketrans({
    "\u00b0": " degrees ",   # ° → degrees
    "\u2013": "-",           # – (en dash) → -
    "\u2014": "-",           # — (em dash) → -
    "\u2018": "'",           # ' → '
    "\u2019": "'",           # ' → '
    "\u201c": '"',           # " → "
    "\u201d": '"',           # " → "
    "\u2026": "...",         # … → ...
    "\u00bd": "1/2",         # ½ → 1/2
    "\u00bc": "1/4",         # ¼ → 1/4
    "\u00be": "3/4",         # ¾ → 3/4
    "\u2153": "1/3",         # ⅓ → 1/3
    "\u2154": "2/3",         # ⅔ → 2/3
})


def clean(s):
    """Collapse whitespace, decode HTML entities, normalise Unicode, and strip."""
    if not s:
        return ""
    s = html.unescape(s)
    s = s.translate(_UNICODE_MAP)
    return re.sub(r"\s+", " ", s).strip()


def best_from_srcset(srcset):
    """Return the highest-resolution URL from an HTML srcset attribute."""
    if not srcset:
        return None
    items = []
    for part in srcset.split(","):
        seg = part.strip().split()
        if not seg:
            continue
        url = seg[0]
        w = 0
        if len(seg) > 1 and seg[1].endswith("w"):
            try:
                w = int(seg[1][:-1])
            except ValueError:
                w = 0
        items.append((w, url))
    if not items:
        return None
    items.sort(key=lambda x: x[0], reverse=True)
    return items[0][1]


def to_float(txt) -> float | None:
    """Extract the first number from *txt* and return it as a float."""
    if txt is None:
        return None
    try:
        m = re.search(r"(\d+(?:[.,]\d+)?)", str(txt))
        if not m:
            return None
        return float(m.group(1).replace(",", "."))
    except (ValueError, TypeError):
        return None


def clean_ingredient_decimals(ingredient: str) -> str:
    """Round long decimals and convert common decimals to fractions."""
    if not ingredient:
        return ingredient

    decimal_pattern = r"\b(\d+)\.(\d{3,})\b"

    def replace_decimal(match):
        whole = match.group(1)
        decimal_part = match.group(2)
        try:
            number = float(f"{whole}.{decimal_part}")
            rounded = round(number, 2)
            if rounded == int(rounded):
                return str(int(rounded))
            return f"{rounded:.2f}".rstrip("0").rstrip(".")
        except (ValueError, TypeError):
            return match.group(0)

    cleaned = re.sub(decimal_pattern, replace_decimal, ingredient)

    fraction_replacements = {
        r"\b0\.33333+\b": "1/3",
        r"\b0\.66666+\b": "2/3",
        r"\b0\.25\b": "1/4",
        r"\b0\.75\b": "3/4",
        r"\b0\.5\b": "1/2",
        r"\b0\.125\b": "1/8",
        r"\b0\.375\b": "3/8",
        r"\b0\.625\b": "5/8",
        r"\b0\.875\b": "7/8",
        r"\b1\.33333+\b": "1 1/3",
        r"\b1\.66666+\b": "1 2/3",
        r"\b2\.33333+\b": "2 1/3",
        r"\b2\.66666+\b": "2 2/3",
    }
    for pattern, replacement in fraction_replacements.items():
        cleaned = re.sub(pattern, replacement, cleaned)

    return cleaned


def iso_duration_to_short(s: str | None) -> str | None:
    """Convert an ISO 8601 duration like 'PT1H30M' to '1 HR 30 MINS'."""
    if not s:
        return None
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s.strip(), re.I)
    if not m:
        m = re.fullmatch(
            r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s.strip(), re.I
        )
    if not m:
        return s
    if m.lastindex == 4:
        d, h, mnt, sec = m.groups()
    else:
        d, h, mnt, sec = None, m.group(1), m.group(2), m.group(3)
    total_min = 0
    if d:
        total_min += int(d) * 24 * 60
    if h:
        total_min += int(h) * 60
    if mnt:
        total_min += int(mnt)
    if sec and not total_min:
        total_min = 1
    if total_min >= 60:
        hrs = total_min // 60
        mins = total_min % 60
        return f"{hrs} HR {mins} MINS" if mins else f"{hrs} HRS"
    return f"{total_min} MINS"
