"""Paizo product-code lookup — script-backed Grimoire add-on.

Looks a Paizo product up by its own product code (SKU), e.g. PZO9001,
PZO1115E, PZOPSS0501E, and fills in what the storefront actually publishes
for that code.

Why a script, not declarative YAML: paizo.com's own search endpoint returns
HTTP 503 for every request in testing (bot-blocked). The live storefront is
store.paizo.com, a BigCommerce site with no JSON API — every field here comes
from parsing the product page's HTML (a schema.org JSON-LD block, plus a
"SKU:"/"UPC:" definition list). That is exactly the case scripts.md reserves
scripts for.

What this fills in, and why not more:
- title: the product's own name, exactly as store.paizo.com titles it (same
  convention the official DriveThruRPG add-on uses — the source's own title,
  not a cleaned-up guess at what belongs in it).
- product_code: the confirmed SKU from the product page, into Grimoire's
  dedicated product-code field (shipped in 1.7.2 — see README).
- publisher: hardcoded to "Paizo Inc." store.paizo.com sells only Paizo's own
  first-party line, so this is a fact about the source, not a guess.
- description: the store's own product description, taken verbatim from the
  page's schema.org/Product JSON-LD block (already decoded, no HTML to
  strip). Same text the ISBN and author patterns below search within.
- isbn: read from an "ISBN-13: ..." line embedded in the description, when
  present. Reliable when it appears.
- authors: read from a "by <name(s)>" line immediately after the product's
  title/chapter heading. This pattern only shows up on Adventure Path
  chapters. Core rulebooks and Pathfinder Society Scenarios do not credit an
  author in their store descriptions at all, so this is left unset for them
  rather than guessed — see README.
- year: deliberately NOT filled. Checked several product types (Adventure
  Path PDFs, core rulebooks, Society Scenarios) and only one, unrelated
  product (a 2E core rulebook) exposed a release date on its page. There is
  no reliable date field for the 1E PZO-coded content this add-on targets.
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "Grimoire-paizo-product-code-addon/1.0.0 (+https://github.com/hunter-read/grimoire)"
SEARCH_URL = "https://store.paizo.com/search.php?search_query={q}&section=product"
PRODUCT_URL = "https://store.paizo.com/{slug}/"
REQUEST_TIMEOUT = 15

# A product card in the search results grid: title text + link to the
# product page. Cards do not show the SKU directly, so identity is the
# stable URL slug, not the code the user typed.
_CARD_RE = re.compile(
    r'<h3 class="card-title">\s*<a href="([^"]+)"[^>]*>([^<]+)</a>',
    re.S,
)
# The product's own image filename is usually the SKU, e.g.
# ".../products/5292/15070/PZO9001_500__32560....jpg" — used only to rank
# candidates when a search returns more than one.
_CARD_IMAGE_SKU_RE = re.compile(r"/products/\d+/\d+/([A-Za-z0-9-]+)_")

_JSONLD_PRODUCT_RE = re.compile(
    r'<script type="application/ld\+json">\s*(\{[^<]*?"@type":\s*"Product".*?\})\s*</script>',
    re.S,
)
_SKU_DT_RE = re.compile(r"<dt[^>]*>\s*SKU:\s*</dt>\s*<dd[^>]*>\s*([^<]+?)\s*</dd>", re.S)
_ISBN_RE = re.compile(r"ISBN.?13:?\s*([\d]{3}[\d-]{10,})", re.I)
# "Chapter 3: \"Title\"\nby Author Name" — only Adventure Path chapters use
# this shape. Anchored near the start of the description so a "by ..."
# mention deep in later credits (co-authors, artists) is not mistaken for it.
_AUTHOR_RE = re.compile(r"^.{0,120}?\bby\s+([A-Z][^\r\n]{2,120})", re.S)


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def _code_variants(code: str):
    """The code as given, then one narrow, safe fallback.

    Paizo appends a single printing/edition letter to a SKU (A-E). The store
    search already matches most of those without help, but on the rare code
    it does not, stripping exactly one trailing letter-after-digit is safe.
    Anything wider (e.g. the "D2" in PZO1119D2, a card-set numbering that has
    no relation to PZO1119) risks matching a different, unrelated product, so
    it is deliberately not attempted — an empty result is safer than a wrong
    one.
    """
    code = code.strip().upper()
    variants = [code]
    if re.search(r"(?<=\d)[A-Z]$", code):
        variants.append(code[:-1])
    return variants


def _extract_cards(listing_html: str, wanted_code: str):
    cards = []
    for href, title in _CARD_RE.findall(listing_html):
        href = html.unescape(href).split("?", 1)[0]
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        cards.append({
            "identity": slug,
            "label": html.unescape(title).strip(),
            "url": href,
        })
    # Rank by whether the card's own cover-image filename matches the code
    # the user searched for — the best signal available without fetching
    # every candidate's full page during search.
    img_skus = dict(zip(
        (c["identity"] for c in cards),
        _CARD_IMAGE_SKU_RE.findall(listing_html),
    ))

    def score(card):
        sku = img_skus.get(card["identity"], "")
        if sku.upper() == wanted_code:
            return 0.99
        if sku:
            return 0.6
        return 0.5

    for card in cards:
        card["score"] = score(card)
    cards.sort(key=lambda c: c["score"], reverse=True)
    return cards


def search(query: str, addon_dir: str) -> dict:
    query = (query or "").strip()
    if not query:
        return {"results": []}
    for i, variant in enumerate(_code_variants(query)):
        if i:
            time.sleep(0.5)  # be polite between our own fallback requests
        url = SEARCH_URL.format(q=urllib.parse.quote(variant))
        try:
            listing_html = _get(url)
        except (urllib.error.URLError, TimeoutError) as exc:
            return {"error": f"could not reach store.paizo.com: {exc}"}
        cards = _extract_cards(listing_html, variant)
        if cards:
            return {"results": cards[:10]}
    return {"results": []}


def fetch(identity: str, addon_dir: str) -> dict:
    if not identity:
        return {"error": "no identity given"}
    url = PRODUCT_URL.format(slug=identity)
    try:
        page_html = _get(url)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 400):
            return {"error": "that product is no longer on store.paizo.com"}
        return {"error": f"store.paizo.com returned HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"error": f"could not reach store.paizo.com: {exc}"}

    sku = None
    m = _SKU_DT_RE.search(page_html)
    if m:
        sku = m.group(1).strip()

    m = _JSONLD_PRODUCT_RE.search(page_html)
    description = ""
    product: dict = {}
    if m:
        try:
            product = json.loads(m.group(1))
        except json.JSONDecodeError:
            product = {}
        description = product.get("description", "") or ""
        if not sku:
            sku = product.get("sku")

    fields = {}
    name = product.get("name")
    if name:
        fields["title"] = name
    if sku:
        fields["product_code"] = sku
    fields["publisher"] = "Paizo Inc."
    if description:
        fields["description"] = description.replace("\r\n", "\n").strip()

    isbn_match = _ISBN_RE.search(description)
    if isbn_match:
        fields["isbn"] = isbn_match.group(1)

    author_match = _AUTHOR_RE.match(description)
    if author_match:
        fields["authors"] = [author_match.group(1).strip().rstrip(".")]

    fields["urls"] = [{"label": "Paizo Store", "url": url}]

    return {"fields": fields, "url": url}


def main():
    request = json.load(sys.stdin)
    action = request.get("action")
    addon_dir = request.get("addon_dir", "")
    if action == "search":
        result = search(request.get("query", ""), addon_dir)
    elif action == "fetch":
        result = fetch(request.get("identity", ""), addon_dir)
    else:
        result = {"error": f"unknown action: {action}"}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
