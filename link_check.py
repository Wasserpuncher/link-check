#!/usr/bin/env python3
"""link-check — verify that every link in a file actually resolves.

Reads Markdown, HTML or plain text, pulls out every http(s) URL, requests
each one, and reports the dead ones. The exit status is non-zero when any
link is broken, so it drops straight into CI as a gate.

Standard library only. No dependencies — the problem and urllib.

What it does NOT do (on purpose, so the claim stays honest):
  * It cannot catch a "soft 404" — a page that returns 200 while saying
    "not found". It checks the status line, not the meaning of the body.
  * Bot protection can answer a real link with 403 or 429. Those are
    reported, not hidden; use --allow to accept specific codes.
  * It only checks absolute http(s) URLs, not relative paths or #anchors.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

__version__ = "1.0.0"

# Markdown [text](url), optionally <url> and a "title".
_MD = re.compile(r'\[[^\]]*\]\(\s*<?(https?://[^)\s>]+)>?\s*(?:"[^"]*")?\)')
# HTML href="url" / src='url'
_ATTR = re.compile(r'(?:href|src)\s*=\s*["\'](https?://[^"\']+)["\']', re.IGNORECASE)
# Bare URL anywhere in the text. Parens are allowed and balanced in _clean(),
# so URLs like .../Foo_(bar) survive while a trailing ")" delimiter is trimmed.
_BARE = re.compile(r'https?://[^\s<>"\'\]]+')
# Fenced code blocks (``` ... ``` or ~~~ ... ~~~): examples, not real links.
_FENCE = re.compile(r'```.*?```|~~~.*?~~~', re.DOTALL)

_TRIM = '.,;:!?)]}\'"'


def strip_code_fences(text: str) -> str:
    """Remove fenced code blocks so example URLs in them are not checked."""
    return _FENCE.sub("", text)


def _clean(url: str) -> str:
    """Decode HTML entities and trim trailing punctuation from a raw URL.

    ``&amp;`` etc. are decoded so the URL matches what a browser would request.
    A trailing ``)`` is kept when it balances a ``(`` inside the URL (so
    ``.../Foo_(bar)`` survives) and stripped when it is just a delimiter.
    """
    url = html.unescape(url)
    while url and url[-1] in _TRIM:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def extract_urls(text: str, skip_code: bool = True) -> list[str]:
    """Return the http(s) URLs in *text*, de-duplicated, order preserved.

    By default, URLs inside fenced code blocks are treated as examples and
    skipped; pass ``skip_code=False`` to check those too.
    """
    if skip_code:
        text = strip_code_fences(text)
    found: list[str] = []
    for pat, grp in ((_MD, 1), (_ATTR, 1), (_BARE, 0)):
        for m in pat.finditer(text):
            found.append(m.group(grp))
    seen: set[str] = set()
    out: list[str] = []
    for u in found:
        u = _clean(u)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


@dataclass
class Result:
    url: str
    ok: bool
    status: str  # HTTP code as string, or an error name like "timeout"


def check_url(url: str, timeout: float = 10.0, allow: frozenset[int] = frozenset()) -> Result:
    """Request *url* and say whether it resolves.

    2xx and 3xx count as alive; anything in *allow* also counts as alive.
    A HEAD is tried first (cheap); servers that refuse it fall back to GET.
    """
    headers = {"User-Agent": f"link-check/{__version__} (+https://github.com/Wasserpuncher/link-check)"}

    def alive(code: int) -> bool:
        return 200 <= code < 400 or code in allow

    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Result(url, alive(resp.getcode()), str(resp.getcode()))
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            # Some servers reject HEAD itself (403/405/501) — retry with GET.
            if method == "HEAD" and code in (403, 405, 501):
                continue
            return Result(url, alive(code), str(code))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            if method == "HEAD":
                continue
            reason = getattr(e, "reason", e)
            name = type(reason).__name__ if not isinstance(reason, str) else reason
            return Result(url, False, name)
    return Result(url, False, "unreachable")


def check_text(text: str, timeout: float = 10.0, workers: int = 8,
               allow: frozenset[int] = frozenset(), skip_code: bool = True) -> list[Result]:
    urls = extract_urls(text, skip_code=skip_code)
    if not urls:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(lambda u: check_url(u, timeout, allow), urls))


def _parse_allow(value: str) -> frozenset[int]:
    if not value:
        return frozenset()
    return frozenset(int(p) for p in value.replace(" ", "").split(",") if p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check that every http(s) link in a file resolves.")
    ap.add_argument("files", nargs="+", help="files to scan (Markdown, HTML, text)")
    ap.add_argument("--timeout", type=float, default=10.0, help="per-request timeout in seconds")
    ap.add_argument("--workers", type=int, default=8, help="number of parallel requests")
    ap.add_argument("--allow", default="", help="extra status codes to treat as OK, e.g. 403,429")
    ap.add_argument("--include-code", action="store_true",
                    help="also check URLs inside fenced code blocks (skipped by default)")
    ap.add_argument("--quiet", action="store_true", help="only print broken links")
    ap.add_argument("--version", action="version", version=f"link-check {__version__}")
    args = ap.parse_args(argv)

    allow = _parse_allow(args.allow)
    broken_total = 0
    checked_total = 0

    for path in args.files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as e:
            print(f"link-check: cannot read {path}: {e}", file=sys.stderr)
            return 2

        results = check_text(text, args.timeout, args.workers, allow,
                             skip_code=not args.include_code)
        checked_total += len(results)
        broken = [r for r in results if not r.ok]
        broken_total += len(broken)

        if not args.quiet:
            print(f"{path}: {len(results)} link(s), {len(broken)} broken")
            for r in results:
                if r.ok:
                    print(f"  ok   {r.status:>4}  {r.url}")
        for r in broken:
            print(f"  DEAD {r.status:>4}  {r.url}")

    print(f"\n{checked_total} link(s) checked, {broken_total} broken.")
    return 1 if broken_total else 0


if __name__ == "__main__":
    sys.exit(main())
