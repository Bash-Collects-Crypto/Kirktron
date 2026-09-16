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

Fixable-by-API items are done. These need account-owner access or a business decision:

- **CJ auto-fulfillment is not on.** Nothing ships automatically until runbook
  §2.1 is done, including funding the CJ Wallet.
- **Shopify policy fields are empty.** Content is in `policies/` awaiting three
  copy-pastes, and lives in parallel as storefront pages. Checkout links to the
  fields, not the pages.
- **Store is still named "My Store 2"** in Shopify settings. The Admin API exposes
  shop settings as read-only, so this can only be changed in the admin UI.
- **Shipping rates are unset.** This is a pricing decision, not a defect — pick a
  flat rate, a free-shipping threshold and a separate heavy-item rate. See
  runbook §2.3.
- **Six overlapping dropshipping importer apps are installed.** Running more than
  one risks double-fulfilling an order. App uninstalls are not exposed to the
  Admin API, so this is a manual cleanup. See runbook §2.7.
- **Two orphaned manual collections** (`graded-card-cases`,
  `card-storage-binders`) are now superseded by the rule-based collections and are
  no longer in any menu. Safe to delete, left in place rather than destroy data.
- **The Magnetic Graded Slab Holder description** was written from title and
  variant data only and needs verification against the CJ source listing.
- **The live theme could not be edited** — theme file writes to the published
  theme are blocked, so this work covers content and structure, not visual design.

A mock storefront page that was live on the store has been unpublished; see
runbook §5 for what it contained and why.
