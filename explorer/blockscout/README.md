# Blockscout for the demo chain

An independent, read-only block explorer for the demo's Anvil chain. It runs beside the Bursar
stack, joins its compose network, and indexes from genesis — so the USDC token page shows the
household treasury and each payee as real holders, and every payment resolves to a transaction.

```bash
# from the repository root, with the Bursar stack already up
docker compose -f explorer/blockscout/anvil.yml -p bursar-explorer up -d
open http://localhost:4000
```

The first start pulls the Blockscout images and indexes the chain (a few minutes); after that the
indexer keeps up block by block.

## What to show

- **Token page** — `Tokens → Test USD Coin (USDC)` or
  `http://localhost:4000/token/<BURSAR_USDC_ADDRESS>`, Holders tab: the treasury (settlement
  operator) and the four payees, with amounts. This is the wallet, outside the app.
- **Transaction page** — `http://localhost:4000/tx/<tx_hash>`: status, block, from/to, the
  `Anchored` log. The gate's tx hash links straight here.
- **Address page** — `http://localhost:4000/address/<address>`: balance and transfers.

## Branding

The UI is the standard Blockscout frontend — no fork and no injected CSS. It is branded through the
runtime theme hooks Blockscout ships:

| Env (in `anvil.yml`) | What it does |
|---|---|
| `NEXT_PUBLIC_COLOR_THEME_OVERRIDES` | The Bursar palette: paper background, ink text, forest links, pink primary buttons, mint selection, pink chart line. |
| `NEXT_PUBLIC_FONT_FAMILY_HEADING` / `_BODY` | Bricolage Grotesque and Instrument Sans, loaded from Google Fonts. |
| `NEXT_PUBLIC_NETWORK_LOGO` / `_DARK` | `file:///app/local/bursar-logo.svg`; the startup script copies it into the app's static assets, so no public URL is needed. |
| `NEXT_PUBLIC_NAVIGATION_LAYOUT` | `horizontal`, so the logo and nav sit in one top bar like the Bursar pages. |
| `NEXT_PUBLIC_HOMEPAGE_HERO_BANNER_CONFIG` | The dark hero with the pink title. |
| `NEXT_PUBLIC_AD_BANNER_PROVIDER` | `none` — no third-party ads. |

Color overrides and fonts are JSON strings parsed with `JSON.parse`, so keep the double quotes. The
logo is `bursar-logo.svg` in this directory and is mounted into the frontend container.

## Networking

The compose file defaults to the demo's network (`bursar_default`) and the Anvil service
(`http://anvil:8545`). It publishes the explorer on `:4000`; on another host or VPS:

```bash
EXPLORER_HOST=demo.example.com EXPLORER_PORT=4000 \
  docker compose -f explorer/blockscout/anvil.yml -p bursar-explorer up -d
```

and build the app with `PUBLIC_EXPLORER_URL=https://demo.example.com:4000` so its links point at
the same place. Do **not** publish Anvil's `8545` publicly: the explorer reaches it inside the
compose network, and an open Anvil RPC accepts unsigned transactions from anyone.

## Resetting

The explorer database is indexed from the chain. If you recreate the chain (`docker compose down -v`
or a fresh Anvil), reset the explorer too or it will hold blocks that no longer exist:

```bash
docker compose -f explorer/blockscout/anvil.yml -p bursar-explorer down -v
```

## Attribution

The compose services and environment templates here are adapted from the Blockscout repository's
own `docker-compose/` tree (github.com/blockscout/blockscout), which is GPL-3.0. The images are
pulled unchanged from `ghcr.io/blockscout/*`. Bursar itself remains MIT; this directory is a
deployment adapter for the demo.
