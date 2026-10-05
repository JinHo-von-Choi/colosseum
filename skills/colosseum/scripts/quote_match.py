"""Check a quoted passage against page text (matcher quote-match/2).

Only display differences are normalized: Unicode compatibility forms (NFKC), case,
whitespace, curly quotes, dash and minus variants, and Markdown markup. Text is then
split into tokens. Words and numbers become tokens; a number keeps its sign, decimal
part, percent sign and attached unit ("-5.2%", "50명", "10kg"); comparison and
currency symbols stay as their own tokens. Other punctuation separates tokens.

  v : the quote's tokens appear as one contiguous run in the page, and the sentence
      around that run carries no condition or scope word the quote left out
  n : review required, never counted as checked. Either a near match (most of the
      quote's tokens in order inside one page window, numbers, negations and
      comparisons unchanged) or a verbatim run that drops a qualifier such as
      "if ..." or "...경우" from its sentence
  u : anything else, including an empty quote or page

Every result carries a reason, and v and n carry the matched token span.
"""
import json
import sys
import unicodedata

MATCHER_VERSION = "quote-match/2"
NEAR = 0.9
MAX_QUOTE_WORDS = 50

_CHAR_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u2212": "-", "\ufe58": "-", "\ufe63": "-", "\uff0d": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u200b": "",
}
SIGNS = "+-\u00b1"
KEEP_SYMBOLS = set("<>=\u2264\u2265\u2260\u2248$\u20ac\u00a3\u00a5\u20a9%\u2030")
COMPARE_SYMBOLS = set("<>=\u2264\u2265\u2260\u2248")
SENTENCE_END = set("!?\n\u3002")

NEGATIONS = {"not", "no", "never", "none", "nor", "neither", "cannot", "without", "nobody", "nothing", "nowhere",
             "\uc548", "\ubabb", "\ubbf8", "\ube44", "\ubd88", "\ubb34"}
NEGATION_PARTS = ("\uc54a", "\uc5c6", "\uc544\ub2c8", "\ubabb\ud558", "\ubd88\uac00")
COMPARATORS = {"more", "less", "fewer", "greater", "over", "under", "above", "below", "least", "most",
               "than", "exceed", "exceeds", "exceeded", "up", "down", "rose", "fell", "increase", "decrease",
               "increased", "decreased", "higher", "lower", "\uc774\uc0c1", "\uc774\ud558", "\ubbf8\ub9cc",
               "\ucd08\uacfc", "\uc774\ub0b4", "\ub118\uac8c", "\uc774\uc0c1\uc758", "\uc774\ud558\uc758"}
QUALIFIERS = {"if", "unless", "when", "whenever", "only", "except", "excluding", "provided", "assuming", "until",
              "\ub2e8", "\ub2e4\ub9cc", "\ub9cc\uc57d", "\uacbd\uc6b0", "\uacbd\uc6b0\uc5d0", "\uacbd\uc6b0\uc5d0\ub294",
              "\uc870\uac74", "\ud55c\ud574", "\uc81c\uc678\ud558\uace0", "\uc81c\uc678\ud558\uba74"}
QUALIFIER_SUFFIXES = ("\uba74", "\uacbd\uc6b0", "\ub54c", "\ub54c\ub294", "\ub54c\ub9cc", "\ub354\ub77c\ub3c4")


def _is_word(ch):
    return ch == "_" or unicodedata.category(ch)[0] in "LMN"


def _is_digit(ch):
    return unicodedata.category(ch) == "Nd"


def _strip_markdown(text):
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "!" and i + 1 < n and text[i + 1] == "[":
            i += 1
            continue
        if ch == "[":
            close = text.find("]", i + 1)
            if close != -1 and close + 1 < n and text[close + 1] == "(":
                end = text.find(")", close + 2)
                if end != -1:
                    out.append(text[i + 1:close])
                    i = end + 1
                    continue
        out.append(ch)
        i += 1
    lines = []
    for line in "".join(out).split("\n"):
        s = line.lstrip()
        j = 0
        while j < len(s) and s[j] in "#>":
            j += 1
        if j and (j == len(s) or s[j] == " "):
            s = s[j:]
        s = s.lstrip()
        if len(s) > 1 and s[0] in "*-+" and s[1] == " ":
            s = s[2:]
        lines.append(s)
    text = "\n".join(lines)
    return "".join(" " if ch in "*_`~|" else ch for ch in text)


def normalize(text):
    """Display-level normalization; signs, digits, negations and comparisons are untouched."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(_CHAR_MAP.get(ch, ch) for ch in text)
    text = _strip_markdown(text).lower()
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def tokenize(norm):
    """Tokens of normalized text, each with a flag marking a sentence end right after it."""
    toks, ends = [], []
    i, n = 0, len(norm)
    while i < n:
        ch = norm[i]
        prev = norm[i - 1] if i else " "
        signed = (ch in SIGNS and i + 1 < n and _is_digit(norm[i + 1])
                  and not _is_word(prev) and prev not in ".,")
        if signed or _is_digit(ch):
            j = i + 1 if signed else i
            while j < n and _is_digit(norm[j]):
                j += 1
            while j + 1 < n and norm[j] in ".," and _is_digit(norm[j + 1]):
                j += 1
                while j < n and _is_digit(norm[j]):
                    j += 1
            while j < n and (_is_word(norm[j]) or norm[j] in "%\u2030"):
                j += 1
            toks.append(norm[i:j])
            ends.append(False)
            i = j
        elif _is_word(ch):
            j = i
            while j < n and (_is_word(norm[j]) or (norm[j] == "'" and j + 1 < n and _is_word(norm[j + 1]) and j > i)):
                j += 1
            toks.append(norm[i:j])
            ends.append(False)
            i = j
        elif ch in KEEP_SYMBOLS:
            toks.append(ch)
            ends.append(False)
            i += 1
        else:
            if ends and (ch in SENTENCE_END or (ch == "." and (i + 1 >= n or norm[i + 1] in " \n\"')"))):
                ends[-1] = True
            i += 1
    return toks, ends


def _is_negation(t):
    return t in NEGATIONS or t.endswith("n't") or any(p in t for p in NEGATION_PARTS)


def _is_comparator(t):
    return t in COMPARATORS or t in COMPARE_SYMBOLS


def _is_qualifier(t):
    if t in QUALIFIERS:
        return True
    return len(t) >= 2 and not t[0].isascii() and t.endswith(QUALIFIER_SUFFIXES)


def _has_digit(t):
    return any(_is_digit(ch) for ch in t)


def _guarded(tokens):
    return sorted({t for t in tokens if _has_digit(t) or _is_negation(t) or _is_comparator(t)})


def _find(q, p):
    first = q[0]
    for s in range(len(p) - len(q) + 1):
        if p[s] == first and p[s:s + len(q)] == q:
            return s
    return -1


def _sentence(ends, start, end):
    """Token range of the sentence(s) holding tokens [start, end)."""
    lo = start
    while lo > 0 and not ends[lo - 1]:
        lo -= 1
    hi = end
    while hi < len(ends) and not ends[hi - 1]:
        hi += 1
    return lo, hi


def _lcs(a, b):
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def best_window(q, p):
    """(in-order token ratio, window start, window end) of the best page window."""
    if not q or not p:
        return 0.0, 0, 0
    qset = set(q)
    size = len(q) + 3
    best, bs, be = 0.0, 0, 0
    for start in range(0, max(1, len(p) - len(q) + 1)):
        seg = p[start:start + size]
        if len(q) >= 3 and sum(1 for t in seg if t in qset) < NEAR * len(q):
            continue
        ratio = _lcs(q, seg) / len(q)
        if ratio > best:
            best, bs, be = ratio, start, start + len(seg)
            if best == 1.0:
                break
    return best, bs, be


def match(quote, page):
    q, _ = tokenize(normalize(quote))
    p, ends = tokenize(normalize(page))
    words = len(q)
    out = {"matcher": MATCHER_VERSION, "words": words}
    if not q or not p:
        out.update(status="u", score=0.0, reason="empty quote or page")
        return out
    if words > MAX_QUOTE_WORDS:
        out["warning"] = "quote longer than %d words" % MAX_QUOTE_WORDS
    start = _find(q, p)
    if start >= 0:
        end = start + len(q)
        lo, hi = _sentence(ends, start, end)
        dropped = sorted({t for t in p[lo:start] + p[end:hi] if _is_qualifier(t)})
        out.update(score=1.0, span=[start, end])
        if dropped:
            out.update(status="n", kind="qualifier_omitted", reason="quote leaves out part of its sentence that "
                       "carries a condition or scope: %s" % ", ".join(dropped))
        else:
            out.update(status="v", reason="exact")
        return out
    ratio, ws, we = best_window(q, p)
    score = round(ratio, 3)
    out["score"] = score
    window = p[ws:we]
    qset = set(q)
    while window and window[0] not in qset:
        window = window[1:]
    while window and window[-1] not in qset:
        window = window[:-1]
    if score < NEAR:
        out.update(status="u", reason="not found on the page")
        return out
    guard_q, guard_w = _guarded(q), _guarded(window)
    if [t for t in guard_q if _has_digit(t)] != [t for t in guard_w if _has_digit(t)]:
        out.update(status="u", reason="numbers or signs differ from the page")
    elif guard_q != guard_w:
        out.update(status="u", reason="negation or comparison differs from the page")
    else:
        out.update(status="n", kind="near", span=[ws, we], reason="near match; review required")
    return out


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description="Classify a quote against page text as v, n or u.")
    p.add_argument("--quote", help="quoted passage (or use --quote-file)")
    p.add_argument("--quote-file")
    p.add_argument("--page-file", required=True, help="page text or markdown")
    a = p.parse_args(argv)
    quote = a.quote if a.quote is not None else open(a.quote_file, encoding="utf-8").read()
    page = open(a.page_file, encoding="utf-8", errors="replace").read()
    print(json.dumps(match(quote, page), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
