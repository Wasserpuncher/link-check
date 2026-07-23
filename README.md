# link-check

[![check](https://github.com/Wasserpuncher/link-check/actions/workflows/check.yml/badge.svg)](https://github.com/Wasserpuncher/link-check/actions/workflows/check.yml)

**A README says "sources below" and lists ten links. This checks that ten links still answer.**

A dead link is the quietest kind of wrong: the prose still reads fine, the URL still looks like a URL, and nobody notices until a reader clicks it. `link-check` pulls every `http(s)` link out of a file, requests each one, and fails the build if any is dead — so the rot shows up in CI instead of in front of a reader.

It belongs to the same family as [readme-check](https://github.com/Wasserpuncher/readme-check) and [the-claim-checkers](https://github.com/Wasserpuncher/the-claim-checkers): a gap between what a document claims and what is true, turned into a build failure.

## Use

No install, no dependencies — just [the standard library](https://docs.python.org/3/library/urllib.request.html) and Python 3.9+.

```
python link_check.py README.md
python link_check.py *.md *.html --timeout 15 --workers 16
python link_check.py page.html --allow 429    # accept rate-limit responses as alive
```

It reads Markdown, HTML or plain text and finds links three ways: Markdown `[text](url)`, HTML `href=`/`src=`, and bare URLs in running text. URLs inside fenced code blocks are treated as examples and skipped by default — pass `--include-code` to check those too. `2xx` and `3xx` count as alive; a server that refuses a `HEAD` is retried with `GET`. The exit status is `1` if any link is broken and `0` if all resolve:

```
README.md: 5 link(s), 1 broken
  DEAD  404  https://example.com/moved
5 link(s) checked, 1 broken.
```

## In CI

```yaml
- run: python link_check.py README.md --allow 429
```

This repository does exactly that: its own workflow runs `link-check` on this very README on every push. If a link here dies, this repo's badge goes red. It does not get to quietly stop being true.

## What it does *not* do (so the claim stays honest)

- It cannot catch a **soft 404** — a page that returns `200` while the body says "not found". It reads the status line, not the meaning of the page.
- **Bot protection** can answer a real link with `403` or `429`. Those are reported, not hidden; use `--allow` to accept specific codes.
- It checks **absolute `http(s)` URLs** only — not relative paths, `mailto:`, or `#anchors`.

## Tests

Hermetic — a throwaway HTTP server on `localhost`, no network needed:

```
python -m unittest -v
```

## License

MIT — see [LICENSE](LICENSE). Related: [wetter.kaipfstr.de](https://wetter.kaipfstr.de), where every number names the source it came from.
