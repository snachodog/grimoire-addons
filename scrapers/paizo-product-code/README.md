# Paizo Product Code

A `target: book` add-on. Looks a Paizo product up by its own product code
(SKU) — `PZO9001`, `PZO1115E`, `PZOPSS0501E`, and similar — and fills in what
the source actually publishes for that code.

## Why a code lookup, not a title search

Most of this library's Pathfinder files already carry an exact Paizo product
code in the file name, left over from an earlier reorganization. A code is an
exact key. Searching by title (as the `adventure-lookup` add-on does for
D&D-and-clone adventures) risks matching the wrong printing or the wrong
product entirely when two products share a title.

## Source: store.paizo.com, via a script

Two sources were evaluated, as the project brief asked:

- **paizo.com's own search** (`paizo.com/search`) returns HTTP 503 on every
  request tested — it is behind bot protection and unusable as a source.
  The storefront has since moved entirely to **store.paizo.com** (a
  BigCommerce site); old `paizo.com/products/<id>` links now redirect to the
  store's homepage rather than a product page.
- **Archives of Nethys** (`aonprd.com` / `2e.aonprd.com`) has a real,
  unauthenticated Elasticsearch API, but it indexes *rules content* (feats,
  spells, monsters), not *products*. Its `source` category documents do carry
  a product page link and a release date for some entries, but there is no
  product-code field to search on, and 1st-edition-only content (the bulk of
  this library's `PZO`-coded files) is not consistently represented. Rejected
  as a source for this add-on.

**store.paizo.com** was used instead. It has no JSON API — searching
`store.paizo.com/search.php?search_query=<code>&section=product` returns an
HTML results page, and each product page embeds a `schema.org/Product`
JSON-LD block plus a `SKU:` / `UPC:` definition list. Because every field
here comes from parsing that HTML, **this add-on is script-backed**, not
declarative YAML — see `scripts.md` in the background doc for why that
distinction exists.

## What it fills in, and why not more

| Field | Filled? | Notes |
| --- | --- | --- |
| `title` | Yes | The product's own name, exactly as store.paizo.com titles it — same convention the official DriveThruRPG add-on uses (the source's own title, not a cleaned-up guess). Some product names include the source's own format tag, e.g. "... (OGL) PDF"; left as-is rather than stripped. |
| `product_code` | Yes | The confirmed SKU from the product page (e.g. `PZO9001`). |
| `publisher` | Always `Paizo Inc.` | store.paizo.com sells only Paizo's own first-party line, so this is a fact about the source, not a guess. |
| `description` | Yes, when the page has one | The store's own product description, taken verbatim from the page's `schema.org/Product` JSON-LD block. Already plain text (no HTML to strip). |
| `isbn` | When present | Read from an `ISBN-13: ...` line embedded in the product description. Present on most books; absent on some (e.g. Pathfinder Society Scenarios, which are not sold with an ISBN at all). |
| `authors` | Only for Adventure Path chapters | Adventure Path volumes open their description with `Chapter N: "Title"` followed by `by <author>` — a reliable, checkable pattern. **Core rulebooks and Pathfinder Society Scenarios do not credit an author anywhere in their store description.** Left unset for those rather than guessed. |
| `year` | **Not filled** | Checked Adventure Path PDFs, core rulebook PDFs, and Society Scenarios — none of them expose a release date on the page. Only one unrelated product checked during this build (a 2nd-edition core rulebook, not part of this library's target content) had a "Release Date" field at all. There is no reliable date source for the content this add-on targets, so `year` is left unmapped rather than filled from an inconsistent field. |
| `urls` | Yes | Adds the store product page link (merges with whatever links the book already has — Grimoire does not overwrite `urls`). |

## Product code field

Grimoire 1.7.2 shipped the real `product_code` field
([issue #479](https://github.com/hunter-read/grimoire/issues/479)). This
add-on maps the confirmed SKU there directly (`grimoire_min_version: 1.7.2`).

Versions before 1.2.0 wrote the code into `tags` instead, as a workaround
while the field didn't exist yet. If you installed an earlier version and
already have books with a `PZO...`-style tag from this add-on, those need a
one-time manual move into `product_code` — this add-on does not migrate
existing tags on update, it only affects new lookups.

## Known gaps — codes that will not resolve

Tested against 15 real product codes pulled at random from
`books/Pathfinder/1st Edition/` in this library. 12 of 15 (80%) resolved to
the correct product on the first or second attempt. The 3 misses, all
confirmed by hand rather than assumed:

- **`PZOPSS0000E`** — appears four times in this library's file names (with
  different embedded copyright years), and does not exist on the store. This
  looks like a placeholder/bad-data code from whatever originally organized
  these files, not a real Society scenario number.
- **`PZO30097`** ("Tavern Multi-Pack") — a physical accessory product; not
  found under this code on the current storefront (likely discontinued or
  renumbered since it was cataloged).
- **`PZO1119D2`** — this is **not** a printing-suffix variant of `PZO1119`
  (the Beginner Box). `PZO1119D`-prefixed codes belong to an entirely
  separate line of item/spell/combat card decks, which the storefront does
  not expose under a code-based search at all. The script deliberately does
  **not** fall back to the bare `PZO1119` for this case — doing so matches
  an unrelated product (confirmed during testing) rather than failing
  honestly. See "Fallback behaviour" below.

## Fallback behaviour

Paizo appends a single printing/edition letter (`A`–`E`) to many SKUs. The
store's own search already tolerates most of these, but on the rare code it
does not, the script retries once with exactly one trailing letter stripped
— only when that letter directly follows a digit. It never strips more than
one character, because a code like `PZO1119D2` looks similar but names a
genuinely different product family; a wider strip would produce a
confident-looking wrong match instead of an honest no-match.

## Paste-a-link support

`search.identity_pattern` lets a user paste a `store.paizo.com` product URL
directly instead of typing the code, going straight to the review step.

## Testing

Sample of 15 real codes tested from this library (see table above for the
match rate). Ran `paizo-product-code.py`'s `search`/`fetch` actions directly
against `store.paizo.com`, matching the exact stdin/stdout contract Grimoire's
`backend/addon_worker.py` uses to invoke it.
