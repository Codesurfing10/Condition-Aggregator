# Condition Aggregator

Web freemium MVP that samples **NOAA / NDBC** buoy observations along an approximate maritime route and summarizes wind/wave conditions. Optional Gemini-powered chat helps interpret the numbers. Accounts + Stripe test-mode subscriptions gate Pro entitlements.

> **⚠ ADVISORY ONLY — NOT FOR NAVIGATION.**  
> Routes are coarse, water-preferring estimates. Conditions are interpolated from public buoy reports and may be incomplete, delayed, or wrong. Always use official nautical charts, notices to mariners, and professional forecasts before going to sea.

## Features

- Plan a start → end route (place names or `lat,lon`)
- **Water-preferring pathfinding** (coarse A* avoiding land polygons) with graceful straight-line fallback
- Sample nearby **NDBC** stations for wind, gusts, waves, period, temps, pressure
- Dark maritime map (Esri Ocean basemap) + Plotly condition chart
- Optional maritime AI assistant (Gemini) when `GEMINI_API_KEY` is set
- **Accounts** (email + password, HTTP-only session cookie) stored in SQLite (`data/app.db`)
- **Freemium quotas** enforced server-side on `/api/route`, `/api/chat`, `/api/saved-routes`
- **Stripe Checkout** (test mode) for Pro subscription + webhook entitlement flips
- West-Coast demo presets (San Diego → San Francisco, Solana Beach → Catalina)

## Stack

| Layer | Tech |
|-------|------|
| API | FastAPI + Uvicorn + SQLAlchemy (SQLite) |
| Auth | passlib/bcrypt + signed JWT session cookie |
| Billing | Stripe Checkout + Customer Portal (test mode) |
| Frontend | Vanilla JS (ES modules), Leaflet, Plotly |
| Data | NOAA NDBC, Nominatim (OSM), Esri Ocean tiles |
| Optional | Google Gemini (`google-generativeai`) |

## Freemium quotas (UTC day)

| Entitlement | Anonymous | Free (signed in) | Pro |
|-------------|-----------|------------------|-----|
| Routes / day | 3 | 3 | 500 |
| AI chats / day | 0 (sign up) | 1 | 100 |
| Saved routes | 0 | 3 | 100 |
| Live buoys | ✓ | ✓ | ✓ |
| Forecasts flag | — | — | ✓ (placeholder) |

Over quota → **402** (free/anon, with upgrade messaging) or **429** (Pro daily cap). Burst IP rate limit (`RATE_LIMIT_PER_MINUTE`) is separate.

## Quick start (local)

### 1. API

```bash
cd Condition-Aggregator
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # edit as needed — never commit .env

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health check: `GET http://127.0.0.1:8000/health` (public; reports `paypal_configured` / `stripe_configured` / `billing_provider`).

Sanity script (no live Stripe keys needed):

```bash
python scripts/sanity_auth_billing.py
```

### 2. Frontend

```bash
# from repo root, with API already running
python3 -m http.server 5500
# open http://127.0.0.1:5500/
```

The UI defaults to `http://127.0.0.1:8000` on localhost. Override with `?api=…` or `localStorage CA_API_BASE`. Session cookies require `credentials: 'include'` (already wired) and matching `CORS_ORIGINS` / `FRONTEND_ORIGIN`.

## PayPal sandbox setup (primary)

Billing prefers **PayPal** when `PAYPAL_CLIENT_ID` + `PAYPAL_CLIENT_SECRET` are set. Stripe paths remain in the codebase but the Upgrade button uses PayPal first.

1. Open [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/) → **Apps & Credentials** → **Sandbox**.
2. Create (or open) a REST app → copy **Client ID** and **Secret**.
3. Put them in `.env` (never commit real secrets):

```bash
PAYPAL_CLIENT_ID=your-sandbox-client-id
PAYPAL_CLIENT_SECRET=your-sandbox-secret
PAYPAL_MODE=sandbox
PAYPAL_PLAN_ID=
APP_BASE_URL=http://127.0.0.1:8000
FRONTEND_ORIGIN=http://127.0.0.1:5500
SESSION_SECRET=some-long-random-string
```

4. **Plan ID**: leave `PAYPAL_PLAN_ID` empty. On first API use (or startup), the app creates a Catalog **product** + monthly **~$12 USD** billing plan via PayPal REST v2 and writes the plan id back into `.env`. You can also create a plan in the Dashboard and paste `P-…` yourself.

5. Create a **Sandbox personal (buyer)** account under **Sandbox → Accounts** (or use the default buyer). Note its email/password for checkout.

6. In the app: **Sign up → Upgrade to Pro** → approve the subscription with the sandbox buyer.  
   On return, the UI calls `POST /api/paypal/capture` with `subscription_id`. When status is `ACTIVE`, the user is set to `plan=pro` (same entitlement model as Stripe).  
   Optional: register a webhook to `https://your-host/api/paypal/webhook` for `BILLING.SUBSCRIPTION.*` events and set `PAYPAL_WEBHOOK_ID` so signatures are verified. Locally, capture-on-return is enough.

7. Cancel/suspend in the sandbox buyer’s PayPal account → webhook (or a later capture/status check) sets `plan=free`.

Sanity (prints OAuth success/fail only — never tokens/secrets):

```bash
# with API deps installed and .env filled
python -c "from app import config, paypal_billing; print('oauth', 'success' if paypal_billing.oauth_ok() else 'fail'); print('plan', paypal_billing.ensure_plan_id()[:8]+'…' if config.paypal_configured() else 'n/a')"
```

Without PayPal keys the API still runs: free tier + accounts work; Upgrade explains config (or falls back to Stripe if those keys are set).

## Stripe test setup (optional / de-emphasized)

Stripe Checkout + Customer Portal remain available when PayPal is **not** configured. See `.env.example` for `STRIPE_*` variables. Test card `4242 4242 4242 4242`; webhook via `stripe listen --forward-to localhost:8000/api/stripe/webhook`. Prefer PayPal for current development.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CORS_ORIGINS` | localhost + Pages | Allowed browser origins (credentials enabled) |
| `APP_BASE_URL` | `http://127.0.0.1:8000` | API public URL |
| `FRONTEND_ORIGIN` | `http://127.0.0.1:5500` | Success/cancel + portal return URL |
| `SESSION_SECRET` | ephemeral | JWT cookie signing (set in prod) |
| `API_KEY` | _(empty)_ | Optional shared `X-API-Key` |
| `RATE_LIMIT_PER_MINUTE` | `60` | Burst IP limit |
| `FREE_*` / `PRO_*` / `ANON_*` | see table | Daily freemium caps |
| `GEMINI_API_KEY` | _(empty)_ | Enables `/api/chat` |
| `PAYPAL_CLIENT_ID` | _(empty)_ | Sandbox REST client id |
| `PAYPAL_CLIENT_SECRET` | _(empty)_ | Sandbox REST secret |
| `PAYPAL_MODE` | `sandbox` | `sandbox` or `live` |
| `PAYPAL_PLAN_ID` | _(empty)_ | Billing plan id (`P-…`); auto-created if empty |
| `PAYPAL_WEBHOOK_ID` | _(empty)_ | Optional webhook verification id |
| `STRIPE_SECRET_KEY` | _(empty)_ | Optional Stripe test secret |
| `STRIPE_PUBLISHABLE_KEY` | _(empty)_ | Optional Stripe publishable |
| `STRIPE_PRICE_ID_PRO` | _(empty)_ | Optional Stripe Price ID |
| `STRIPE_WEBHOOK_SECRET` | _(empty)_ | Optional Stripe webhook secret |
| `DATABASE_URL` | `sqlite:///…/data/app.db` | SQLAlchemy URL |

See `.env.example`. **Do not commit secrets.** `data/app.db` is gitignored.

## API overview

| Method | Path | Auth / limits | Notes |
|--------|------|---------------|-------|
| `GET` | `/health` | Public | Liveness + chat/Stripe flags |
| `GET` | `/api/me` | Cookie optional | User + quota snapshot |
| `POST` | `/api/auth/signup` | Public | Sets session cookie |
| `POST` | `/api/auth/login` | Public | Sets session cookie |
| `POST` | `/api/auth/logout` | Cookie | Clears session |
| `GET` | `/api/billing/status` | Cookie optional | Plan + paypal/stripe flags |
| `POST` | `/api/paypal/create-subscription` | Signed in | PayPal approval URL + subscription id |
| `POST` | `/api/paypal/capture` | Signed in | Mark Pro when subscription ACTIVE |
| `POST` | `/api/paypal/webhook` | PayPal webhook | Entitlement flips |
| `POST` | `/api/billing/checkout` | Signed in | Stripe Checkout (fallback) |
| `POST` | `/api/billing/portal` | Signed in | Stripe Customer Portal |
| `POST` | `/api/stripe/webhook` | Stripe signature | Stripe entitlement flips |
| `GET/POST/DELETE` | `/api/saved-routes` | Signed in + quota | Favorites |
| `POST` | `/api/route` | Rate limit + daily quota | Optional water `path` |
| `POST` | `/api/chat` | Rate limit + daily quota | Needs Gemini; free needs account |
| `GET` | `/api/geocode` | Rate limit | Nominatim proxy |
| `GET` | `/api/stations/near` | Rate limit | Nearby NDBC |
| `GET` | `/api/conditions` | Rate limit | Station observation |

## Deploy notes

- **API (e.g. Render):** `render.yaml` runs `uvicorn app.main:app`. Set secrets in the host dashboard (`SESSION_SECRET`, Stripe test/live keys, `CORS_ORIGINS`, `FRONTEND_ORIGIN`, `GEMINI_API_KEY`, …). Use a persistent disk for `data/app.db` or switch `DATABASE_URL` to Postgres for production.
- **Frontend:** Static host serving `index.html`, `app.js`, `src/`, `data/`. Point UI at API via `?api=` / `CA_API_BASE`. Cross-origin cookies need HTTPS + appropriate `COOKIE_SAMESITE` / `COOKIE_SECURE`.
- **Land polygons:** `data/land_110m.geojson` powers water routing.

## Attribution

- **NOAA / NDBC** — buoy stations and realtime observations  
- **Nominatim / OpenStreetMap** — geocoding  
- **Esri** — Ocean basemap & reference tiles  
- Natural Earth–derived land polygons for coarse water routing  
- **PayPal** — sandbox subscriptions (primary billing)  
- **Stripe** — optional test-mode billing  

This project is not affiliated with NOAA, NDBC, Esri, OpenStreetMap, PayPal, or Stripe.

## License

MIT © 2026 Codesurfing10 / James Gallagher — see [LICENSE](./LICENSE).

## Still needed for production launch

- Live PayPal (or Stripe) keys, public webhook endpoint, cancel/manage UX hardening
- Persistent DB (Postgres) + backups; rotate `SESSION_SECRET`
- HTTPS everywhere; harden cookie flags (`COOKIE_SECURE=true`, SameSite strategy for your domains)
- Legal review of advisory disclaimers; ToS / Privacy / refund policy
- Email verification, password reset, abuse monitoring
- Replace Gemini deprecated client (`google.genai`) when convenient
- Optional: forecasts product behind `forecasts_enabled`
