"""Check a quoted passage against page text.

Normalization follows the verified-quote check used in LLM debate experiments
(curly quotes to straight, punctuation removed, lowercase, whitespace collapsed),
plus Unicode NFKC and Markdown stripping.

  v : the normalized quote is a substring of the normalized page
  n : the best-matching page window contains at least NEAR of the quote's words in
      order (longest common subsequence), and every number in the quote appears there
  u : anything else, including an empty quote or page
"""
import json
import re
import sys
import unicodedata

NEAR = 0.9
MAX_QUOTE_WORDS = 50

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MD_MARK = re.compile(r"(^|\s)[#>*\-+]+\s|[*_`~|]+")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize(text):
    text = unicodedata.normalize("NFKC", text or "").translate(_QUOTES)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_MARK.sub(" ", text)
    text = _NON_WORD.sub(" ", text).lower()
    return _SPACE.sub(" ", text).strip()


def _trigrams(words):
    return [tuple(words[i:i + 3]) for i in range(len(words) - 2)] or ([tuple(words)] if words else [])


def _lcs(a, b):
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def best_window(quote_norm, page_norm):
    """(in-order word match ratio, window words) for the best page window.

    Windows are screened by word 3-gram overlap first, so only plausible
    candidates pay for the quadratic subsequence comparison.
    """
    q = quote_norm.split()
    p = page_norm.split()
    if not q or not p:
        return 0.0, []
    qg = set(_trigrams(q))
    size = len(q) + 5
    page_grams = _trigrams(p)
    best, best_seg = 0.0, []
    for start in range(0, max(1, len(p) - len(q) + 1)):
        grams = page_grams[start:start + size]
        if len(q) >= 3 and sum(1 for g in grams if g in qg) < max(1, len(qg) // 5):
            continue
        seg = p[start:start + size]
        ratio = _lcs(q, seg) / len(q)
        if ratio > best:
            best, best_seg = ratio, seg
            if best == 1.0:
                break
    return best, best_seg


def match(quote, page):
    qn, pn = normalize(quote), normalize(page)
    words = len(qn.split())
    if not qn or not pn:
        return {"status": "u", "score": 0.0, "words": words, "reason": "empty quote or page"}
    if f" {qn} " in f" {pn} ":
        return {"status": "v", "score": 1.0, "words": words}
    ratio, window = best_window(qn, pn)
    numbers = {w for w in qn.split() if any(ch.isdigit() for ch in w)}
    numbers_ok = numbers <= set(window)
    score = round(ratio, 3)
    result = {"status": "n" if score >= NEAR and numbers_ok else "u", "score": score, "words": words}
    if not numbers_ok:
        result["reason"] = "numbers differ from the page"
    if words > MAX_QUOTE_WORDS:
        result["warning"] = "quote longer than %d words" % MAX_QUOTE_WORDS
    return result


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
