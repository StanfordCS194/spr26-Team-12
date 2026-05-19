# Deploying Veritas

A complete walkthrough from a local repo to live URLs on Render (backend) and
Vercel (frontend). Free tier, no credit card required.

The end state:

```
Frontend  →  https://veritas-<hash>.vercel.app          (or your custom domain)
Backend   →  https://veritas-api.onrender.com           (or your custom subdomain)
```

The frontend uses Vercel rewrites to proxy `/api/*` to the backend, so
browser requests stay same-origin and you don't need to configure CORS.

---

## 0 · Pre-flight (1 minute)

Make sure these files exist on your branch (this PR adds them):

- `Dockerfile` at repo root — builds the backend image for Render
- `.dockerignore` — keeps the image small
- `frontend/vercel.json` — tells Vercel to proxy `/api/*` to Render

---

## 1 · Deploy the backend on Render (~10 minutes)

1. Go to <https://render.com> → **Get Started** → sign up with GitHub.
2. Click **New +** (top right) → **Web Service**.
3. **Connect a repository** → authorize Render to read your GitHub account
   → pick `StanfordCS194/spr26-Team-12`.
4. Fill in the form:

   | Field | Value |
   |---|---|
   | Name | `veritas-api` |
   | Region | `Oregon (US West)` |
   | Branch | `main` |
   | Root Directory | leave blank |
   | Runtime | `Docker` (Render auto-detects from the Dockerfile) |
   | Instance Type | `Free` |

5. Scroll down to **Environment Variables**. Click **Add Environment Variable**
   for each one you have:

   | Key | Value | Required? |
   |---|---|---|
   | `DEMO_MODE` | `true` | No — set to `false` once you have API keys |
   | `OPENAI_API_KEY` | `sk-...` | Only if you have one. Skip otherwise. |
   | `GROQ_API_KEY` | `gsk_...` | Only if you have one. Skip otherwise. |
   | `TAVILY_API_KEY` | `tvly-...` | Only if you have one. Skip otherwise. |

   With `DEMO_MODE=true` (or no keys) the pipeline runs in fallback mode —
   the cached verdicts and seeded influencers still work, which is plenty for
   a demo. Real live fact-checking against new clips requires the API keys.

6. *(Optional — recommended)* Scroll to **Advanced** → **Disks** → **Add Disk**:

   - **Name:** `data`
   - **Mount Path:** `/app/backend/data`
   - **Size:** 1 GB

   This makes the seeded influencers, products, and the credibility ledger
   survive restarts. Without a disk, each redeploy resets to the seeded state.

7. Click **Create Web Service**. Render builds the Docker image (takes
   ~3–5 minutes the first time). Watch the **Logs** tab.

8. When it says **Live**, copy the URL at the top — something like
   `https://veritas-api.onrender.com`. Verify it works:

   ```
   curl https://veritas-api.onrender.com/api/health
   ```

   You should see a JSON response with `"ok": true`.

   On the free tier, the service sleeps after ~15 minutes of inactivity. The
   first request after a sleep takes ~30 seconds while it spins back up. Hit
   the URL above 60 seconds before any demo to wake it.

---

## 2 · Point the frontend at your Render URL

If your Render URL is not exactly `https://veritas-api.onrender.com`, you need
to update one line in `frontend/vercel.json`:

```json
{
  "rewrites": [
    {
      "source": "/api/:path*",
      "destination": "https://YOUR-RENDER-URL/api/:path*"
    }
  ]
}
```

Commit and push that change to your branch.

---

## 3 · Deploy the frontend on Vercel (~5 minutes)

1. Go to <https://vercel.com> → **Sign Up** with GitHub.
2. On the dashboard, click **Add New…** → **Project**.
3. **Import Git Repository** → find `StanfordCS194/spr26-Team-12` → **Import**.
4. Configure project:

   | Field | Value |
   |---|---|
   | Project Name | `veritas` |
   | Framework Preset | `Vite` (auto-detected) |
   | Root Directory | `frontend` |
   | Build Command | leave default (`npm run build`) |
   | Output Directory | leave default (`dist`) |
   | Install Command | leave default |

5. Click **Deploy**. Vercel builds and ships in ~2 minutes.

6. When done, click the screenshot of the live site. You'll be on something
   like `https://veritas-abcd1234.vercel.app`.

7. Open `/api/health` on that URL (e.g. <https://veritas-abcd1234.vercel.app/api/health>)
   to confirm the proxy is wired — same JSON as in step 1.8.

8. Navigate to `/` and click through **Fact Check / Influencers / Products**.
   You're live.

---

## 4 · Optional polish (any time later)

### Custom domain

1. Buy a domain on Namecheap or Cloudflare (~$10/year for `.com`).
2. In Vercel project → **Settings** → **Domains** → add `veritas.yourname.com`.
3. Vercel shows the DNS records to add at your registrar (one CNAME).
4. *(Optional)* In Render → **Settings** → **Custom Domains** → add
   `api.veritas.yourname.com`. Update `frontend/vercel.json` to point at it.

### Avoiding the free-tier cold start

Upgrade Render to the **Starter** plan ($7/mo) for always-on. Same service,
no other changes needed. Or use a free pinger service like
<https://cron-job.org> to ping `/api/health` every 14 minutes.

### Production API keys

Add `OPENAI_API_KEY`, `GROQ_API_KEY`, `TAVILY_API_KEY` to Render's environment
and set `DEMO_MODE=false`. Render redeploys automatically.

### Chrome extension

Load **Load unpacked** from `chrome-extension/` (see `chrome-extension/README.md`).
Production API is the default backend; `manifest.json` includes
`https://veritas-api.onrender.com/*` in `host_permissions`.

After you have a public Vercel URL from §3, add **`PUBLIC_WEB_APP_URL`** on Render
(same value, no trailing slash). `/api/health` then includes `web_app_url`, so
the extension can open the full app and **Test connection** in Settings can
fill the frontend URL when it is still localhost.

---

## Troubleshooting

**Render build fails with "fastapi not found"** — Make sure Render's *Runtime*
is set to `Docker`. If it's set to `Python` it ignores the Dockerfile and tries
its own build that doesn't know where `backend/requirements.txt` is.

**Vercel build fails with "Cannot find module"** — Make sure *Root Directory*
is set to `frontend` in Vercel project settings.

**`/api/health` returns 404 on the Vercel URL but works on the Render URL** —
`vercel.json` needs to live inside the `frontend/` directory (the one set as
the Vercel root). Check that the rewrite `destination` is the exact Render URL.

**`/api/clip-report` times out** — Render's free tier has a 100-second request
limit and the LLM-driven fact-check can exceed that with cold caches.
First fact-check after a wake-up may need a retry; subsequent ones are fast.
