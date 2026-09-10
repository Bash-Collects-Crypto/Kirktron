# Kirktron
Programs to build crypto bot and system to help performance

## pokehunt

Alert-only scanner for underpriced Pokémon card auctions on eBay: discovers the
real category ids from eBay's Taxonomy API, filters to auctions ending within
24 hours with few watchers and low-feedback sellers, reads the listing photos
with a vision model, prices the identified cards against pokemontcg.io, and
posts to Discord with a red flag on anything it is not confident about.

It does not bid. It records every alert so that after a month you can score the
estimates against what the lots actually sold for, and find out whether the
recognition layer is good enough to trust with money.

See [`pokehunt/README.md`](pokehunt/README.md).
