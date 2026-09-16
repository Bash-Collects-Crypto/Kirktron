# Kirktron — Bash Collectibles Store Configuration

Configuration, copy and operating documentation for the **Bash Collectibles**
Shopify store (`3kcy0r-q2.myshopify.com`) — a trading-card storage and display
shop fulfilled through CJdropshipping.

## Contents

| Path | What it is |
|---|---|
| [`docs/store-runbook.md`](docs/store-runbook.md) | What is configured, what still needs account-owner access, tagging conventions, monthly ops checklist |
| [`docs/product-sourcing.md`](docs/product-sourcing.md) | Which products to import from CJ and why, with margin rules and target price points |
| [`policies/`](policies/) | Policy HTML ready to paste into Shopify Settings → Policies |

## Start here

1. **`docs/store-runbook.md` §2** — the ordered list of things only you can do.
   Nothing in this store ships an order until §2.1 (CJ auto-fulfillment) is done.
2. **`docs/product-sourcing.md`** — before importing anything else from CJ.

## How the storefront organises itself

Collections are **rule-based, not manual lists**. A product imported from CJ files
itself into every collection whose rule it matches — by tag, by keyword in its
title, or by price. The two price collections (`Under $25`, `Premium Displays`)
need no tagging at all.

Adding tags at import time makes the filing precise; see the tagging convention in
the runbook. The one collection that requires tags is `Graded Slab Displays`, which
uses AND logic and needs both `graded-slabs` and `display`.

## Known gaps

- Shopify policy **fields** are empty — content lives in `policies/` awaiting three
  copy-pastes, and in parallel as storefront pages. Checkout links to the fields,
  not the pages.
- Store is still named "My Store 2" in Shopify settings.
- Six overlapping dropshipping importer apps are installed; running more than one
  risks double-fulfilling an order. See runbook §2.7.
- The Magnetic Graded Slab Holder description was written from title and variant
  data only and needs verification against the CJ source listing.
