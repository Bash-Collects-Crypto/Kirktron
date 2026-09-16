# Bash Collectibles — Store Runbook

Store: `3kcy0r-q2.myshopify.com` · Plan: Basic · Currency: USD · Niche: trading-card storage & display

This is the operating manual for the store. It records what is already configured,
what only a human with account access can do, and the conventions that keep the
storefront organising itself as new products arrive.

---

## 1. What is already live

### Storefront pages
| Page | Handle |
|---|---|
| Shipping & Delivery | `/pages/shipping-policy` |
| Refund & Return Policy | `/pages/refund-policy` |
| Terms of Service | `/pages/terms-of-service` |
| FAQ | `/pages/faq` |
| About Us | `/pages/about` |

The FAQ is written to absorb the three questions that generate the most support
email on a dropshipped store: *where is my order*, *why is tracking not moving*,
and *will this fit my slab*. Keep it current — every question it answers is an
email you do not have to write.

### Collections (all rule-based / self-filing)
| Collection | Handle | Rule |
|---|---|---|
| Graded Slab Displays | `graded-slab-displays` | tag `graded-slabs` **AND** tag `display` |
| Wall Mount Displays | `wall-mount-displays` | tag `wall-mount` OR title contains "wall mount" / "wall-mounted" |
| Card Storage | `card-storage` | tag `storage` OR title contains "toploader" / "sleeve" / "storage box" / "card brick" |
| Binders & Albums | `binders-and-albums` | tag `binder` / `album` OR title contains "binder" / "portfolio" / "album" |
| Pokémon Collectors | `pokemon-collectors` | tag `pokemon` OR title contains "pokemon" / "pokémon" / "ptcg" |
| Sports Card Collectors | `sports-card-collectors` | tag `sports-cards` OR title contains "baseball" / "football" / "basketball" / "hockey" |
| Under $25 | `under-25` | any variant price < $25 |
| Premium Displays | `premium-displays` | any variant price > $50 |

**Why this matters:** these are smart collections, not manual lists. Import a
product from CJ and it files itself into every collection whose rule it matches —
including the two price collections, which need no tagging at all. You never touch
a collection again.

`Graded Slab Displays` is the one exception: it uses AND logic for precision, so a
product must carry **both** `graded-slabs` and `display` tags to appear. Tag
accordingly (see §3).

### Navigation
Main menu and footer menu were rebuilt from the Shopify defaults. Main menu now
carries a `Shop All` dropdown over the four category collections, direct links to
Pokémon / Sports Cards / Under $25 / Premium Displays, and a `Help` dropdown over
FAQ, Shipping, Returns and Contact. The footer carries every policy link.

### Products
All four existing products were normalised: vendor unified to `Bash Collectibles`,
product types set (`Card Storage` / `Card Display`), SEO titles and meta
descriptions written, tags applied, and keyword-stuffed supplier titles rewritten.
The Magnetic Graded Slab Holder had a **completely empty description** and now has
a full one.

> ⚠️ That description was written from the product title and variant data alone,
> because the CJ source listing was not reachable from this environment. **Verify
> its claims against the CJ listing** — specifically the magnetic closure, the
> wall/tabletop dual mounting, and PSA/CSG/CGC fit — before you spend money driving
> traffic to it.

---

## 2. What only you can do

These require account-owner access, an app UI, or a scope the Claude connector
does not hold. Ordered by what blocks revenue soonest.

### 2.1 Turn on CJ auto-fulfillment — *this is the hands-off lever*
Everything else in this repo is presentation. This is the part that means an order
ships without you touching it.

In the **CJdropshipping app** (already installed on the store):
1. **Authorization** — confirm the store is still authorised and syncing.
2. **Pricing Rule** — set a global markup multiplier (see `product-sourcing.md`
   for the multiplier to use). Imported products then price themselves.
3. **Auto Order / Automatic Order Processing** — enable. Paid Shopify orders are
   placed with CJ automatically instead of you clicking each one.
4. **Auto-sync tracking** — enable, so tracking numbers push back to Shopify and
   the customer gets a shipping-confirmation email with no input from you.
5. **Fund the CJ Wallet** or bind a payment method with auto-deduct. Without a
   funded balance, auto-order silently queues and nothing ships. This is the single
   most common way a "hands-off" store quietly stops fulfilling.

Menu labels shift between CJ app versions; these settings live under
Settings / Account in the app.

### 2.2 Payments
Confirm Shopify Payments (or an alternative gateway) is live and a payout bank
account is attached. A store cannot take money until this is done.

### 2.3 Shipping rates
Settings → Shipping and delivery. Set real rates before launch. Recommended:
a flat rate for small accessories, free shipping over a threshold set just above
your current average order value, and a separate higher rate for the heavy
wall-cabinet items. **Free shipping thresholds raise average order value more
reliably than discount codes** in this category.

Note: the Shipping & Delivery page deliberately says *"costs are calculated at
checkout"* rather than promising a threshold, so it stays accurate until you
configure this. If you do set a free-shipping threshold, add it to that page.

### 2.4 Store name
The store is still called **"My Store 2"**. It appears in the browser tab, every
transactional email, and the checkout. The brand everywhere else is
**Bash Collectibles**. Fix in Settings → General → Store name.

### 2.5 Policy fields (3 copy-pastes)
The Claude connector lacks the `write_legal_policies` scope, so the real policy
fields could not be written via API — the content lives as storefront pages
instead. Shopify's **checkout** links to the policy *fields*, not pages, so paste
the HTML from `/policies/` in this repo into Settings → Policies:

| Repo file | Shopify policy field |
|---|---|
| `policies/shipping-policy.html` | Shipping policy |
| `policies/refund-policy.html` | Refund policy |
| `policies/terms-of-service.html` | Terms of service |

Privacy policy is already populated — leave it.

### 2.6 Custom domain
A `myshopify.com` address measurably depresses conversion. Buy a domain and
connect it. While you are there, move support off the personal Gmail address
currently published in the policies to `support@yourdomain`.

### 2.7 Clean up the installed apps — do this before launch
Twelve apps are installed, and **six are overlapping product importers**:
CJdropshipping, TeemDrop, AliExpress Dropshipping Center, Spocket, TCG Importer,
and Storebuild.ai. This is a real problem, not housekeeping:

- Two importers can both claim the same order and **double-fulfill it** — you pay
  twice and the customer gets two parcels.
- Duplicate product records fragment your analytics and can create competing
  listings for the same item.
- App subscriptions stack monthly against a Basic-plan margin.

Pick CJdropshipping as the single source of fulfillment truth and uninstall the
importers you are not using. Keep `Shopify Claude Connector App`.

---

## 3. Tagging convention

CJ imports arrive with supplier titles and **no tags**. The title-contains
fallback rules in §1 catch the common cases, but tagging is what gives you precise
merchandising. Apply these at import:

| Tag | Use for |
|---|---|
| `graded-slabs` | fits PSA / BGS / CGC / SGC graded cases |
| `display` | purpose is showing cards, not storing them |
| `storage` | purpose is holding volume — boxes, bricks, cases |
| `binder` / `album` | binders and album pages |
| `wall-mount` | mounts to a wall |
| `pokemon` / `sports-cards` | audience-specific |
| `psa` / `bgs` / `cgc` / `csg` | specific slab compatibility |
| `uv-protection` | genuinely UV-rated — **only if the supplier states a rating** |
| `lockable` | has a lock |
| `premium` | $50+ hero pieces |

Two rules worth holding to:

**A product for graded slabs needs `graded-slabs` AND `display` to reach the
Graded Slab Displays collection.** One tag alone is not enough.

**Never apply `uv-protection` without a supplier-stated rating.** Collectors buy
specifically on that claim, and an unsupported one is both a chargeback and an
advertising-law problem.

---

## 4. Monthly operating checklist

Hands-off does not mean unattended. Fifteen minutes a month:

- [ ] CJ Wallet still funded? (an empty wallet stops all fulfillment silently)
- [ ] Any CJ products gone out of stock or been discontinued upstream? Set those
      Shopify products to `DRAFT` so you stop selling what you cannot ship.
- [ ] Any order stuck unfulfilled more than 5 days?
- [ ] Skim the analytics: which products actually sold? Kill the dead ones.
- [ ] Spot-check that supplier prices have not risen enough to break your margin.

Out-of-stock upstream is the highest-risk item on this list. Selling something CJ
can no longer supply generates refunds, chargebacks and negative reviews faster
than anything else on a dropshipped store.
