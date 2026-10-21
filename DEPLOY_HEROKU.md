# Deploying AstroSlide to Heroku

Two deploys:

- **Frontend → GitHub Pages** at `https://astroslide.me`. `.github/workflows/pages.yml` builds it on every push to `master` that touches `frontend/`. It's free, and the page loads instantly even while the dyno sleeps.
- **API → one Heroku dyno** at `https://api.astroslide.me`. The root `Dockerfile` builds the backend only. No add-ons (database, Redis, logging) are needed.

The editor fetches `/api/presets` as soon as it opens, which wakes a sleeping dyno while the visitor is still looking at the page.

## Cost

| Dyno | Price | Behaviour |
|------|-------|-----------|
| **Eco** (recommended) | $5/month flat, 1000 hours shared by all your Eco apps | Sleeps after 30 minutes without traffic; the first visit after that waits ~10–20 s while it wakes |
| Basic | up to $7/month (billed per second) | Always on |

Both have 512 MB of RAM and fit within a $13/month credit. Run **one** web dyno, and don't pick Standard or Performance dynos ($25+). Eco can't run over its price; Basic can't exceed $7 for one dyno.

## Deploy

```bash
# once
heroku login
heroku create <app-name> --stack container      # uses heroku.yml + Dockerfile
heroku ps:type web=eco                           # needs the Eco plan (Billing page); or web=basic

# each deploy (Heroku builds from the branch you push to its main);
# without the bigger buffer the push fails with "bad line length character: fata"
git -c http.postBuffer=209715200 push heroku <branch>:main
```

## Domain and frontend (once)

The domain is registered at Namecheap (free `.me` from the GitHub Student Developer Pack).

1. **API domain.** Run `heroku domains:add api.astroslide.me` and note the DNS target it prints (`….herokudns.com`). Then `heroku certs:auto:enable` for HTTPS.
2. **DNS at Namecheap** (Domain List → astroslide.me → Manage → Advanced DNS):
   - keep the GitHub Pages records the student offer created: A records on `@` to `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`, and a `www` CNAME to `astroslide.me`
   - add a CNAME record: host `api`, value the Heroku DNS target
3. **GitHub Pages** (repo Settings → Pages): set Source to **GitHub Actions**, then Custom domain to `astroslide.me` and tick **Enforce HTTPS** once the certificate is ready. With an Actions deploy the domain is set here, not with a `CNAME` file.
4. Run the **Deploy frontend** workflow (Actions tab → Run workflow), or push to `master`.

Check: `curl -sI https://api.astroslide.me/api/health` and open `https://astroslide.me`.

The API accepts browser calls only from `https://astroslide.me` (`ASTROSLIDE_CORS_ORIGINS`). For another frontend address, such as a preview, run `heroku config:set ASTROSLIDE_CORS_ORIGINS="https://astroslide.me,https://other.example"`.

Optional, to see memory use in the logs:

```bash
heroku labs:enable log-runtime-metrics
heroku logs --tail
```

## Sized for 512 MB

The `Dockerfile` sets these defaults. Change them with `heroku config:set NAME=value`.

| Variable | Heroku default | Local default | What it does |
|----------|----------------|---------------|--------------|
| `ASTROSLIDE_THREADS` | 1 | 4 | Image requests processed at once (others wait in line) and stacker worker threads |
| `ASTROSLIDE_MAX_MEGAPIXELS` | 2.1 | no limit | Larger images are downscaled first, and the result says so. A Seestar frame (1920×1080) fits |
| `ASTROSLIDE_MAX_STACK_GB` | 1 | 6 | Video stacking upload limit (raw AVI is ~1 GB per minute) |
| `OPENCV_FOR_THREADS_NUM`, `OMP_NUM_THREADS`, … | 2 | all cores | A dyno sees every core of the host but only gets a share; more threads only cost memory |
| `ASTROSLIDE_MAX_DECODE_MEGAPIXELS` | 16 | 180 | Larger PNG/TIFF/FITS images are refused before decoding (a full 25 MP image runs Mineral Moon out of memory). JPEGs over `ASTROSLIDE_MAX_MEGAPIXELS` decode at 1/2, 1/4 or 1/8 scale instead, so camera JPEGs up to 64× this size work (a 50 MP JPEG peaks at ~385 MB) |
| `ASTROSLIDE_MAX_VIDEO_MEGAPIXELS` | 2.1 | no limit | Videos with larger frames are refused |
| `ASTROSLIDE_MAX_UPLOAD_MB` | 50 | 50 | Image upload limit, checked from the request headers before the upload is read |
| `ASTROSLIDE_MAX_STACK_UPLOADS` | 1 | 2 | Videos received at once; more get "busy, try again" instead of filling the disk |
| `ASTROSLIDE_MAX_STACK_JOBS` | 3 | 4 | Stacking jobs uploading, queued or running at once |

Measured with Docker limited to 512 MB and 1 CPU: Mineral Moon renders in ~1 s, Nebula in 1–3 s, and stacking the sample MP4 (896 frames) takes ~50 s. Four requests at once and a stack running alongside an enhance peaked at ~430 MB, with no out-of-memory kill.

## Security settings

Also set in the `Dockerfile`:

| Variable | Heroku | Local default | What it does |
|----------|--------|---------------|--------------|
| `ASTROSLIDE_FORCE_HTTPS` | 1 | off | Redirects `http://` to `https://` when the router says the request came over http; https responses get HSTS |
| `ASTROSLIDE_CORS_ORIGINS` | `https://astroslide.me` | `*` | Sites allowed to call the API from a browser, comma-separated: the frontend on GitHub Pages. `*` is for the Vite dev server calling `localhost:8000` |
| `ASTROSLIDE_API_DOCS` | 0 | 1 | `/docs`, `/redoc` and `/openapi.json` |
| `ASTROSLIDE_RATE_LIMIT` | 180 | off | Processing budget per client IP, in units per minute (preview/histogram 1, stretch 2, enhance 3); a client can bank two minutes' worth. A fast slider session uses ~170 a minute |
| `ASTROSLIDE_MAX_REQUESTS_PER_CLIENT` | 4 | off | Processing requests one IP can have running or waiting at once, so a busy client can't take over the queue for the single processing slot |
| `ASTROSLIDE_STACK_JOBS_PER_HOUR` | 6 | off | Stacking jobs one IP can start per hour (3 at once) |
| `ASTROSLIDE_PROXY_HOPS` | 1 | 0 | Proxies appending to `X-Forwarded-For`; the client IP is read that many entries from the right, since entries further left are whatever the client sent |

Over-limit requests get `429` with a `Retry-After` header. The limits are kept in the app's memory: they reset on restart, and with more than one dyno or worker each would count separately.

Every API response carries a Content-Security-Policy, `nosniff`, `X-Frame-Options: DENY` and a referrer policy. Check them with `curl -sI https://api.astroslide.me/api/health`. GitHub Pages can't send headers, so the production build puts the same Content-Security-Policy (only this site's scripts, API calls only to `api.astroslide.me`) in a `<meta>` tag (`frontend/vite.config.ts`). Pages can't stop the site being framed.

Outside the app: turn on two-factor authentication for the Heroku account (Account settings → Multi-factor authentication), since anyone with the account can push code to the dyno.

## Limits to know

- **30-second request timeout.** Upload time doesn't count, but processing does. Star removal on a large galaxy image takes ~17–20 s on one CPU, which is close to that limit. Stacking runs as a background job, so it isn't affected.
- **Temporary files.** The disk is wiped whenever the dyno restarts (at least once a day, and on every deploy) or an Eco dyno goes to sleep. Stacking jobs in progress and results not yet downloaded are lost.
- **Memory warnings.** If the logs show `R14 (Memory quota exceeded)`, lower `ASTROSLIDE_MAX_MEGAPIXELS`. `H12 (Request timeout)` means a request needed more than 30 s.

## Test the image locally under dyno limits

```bash
docker build -t astroslide-heroku .
# not port 5000: macOS AirPlay answers there with 403
docker run --rm --memory=512m --memory-swap=512m --cpus=1 -e PORT=8000 -e ASTROSLIDE_CORS_ORIGINS='*' -p 8000:8000 astroslide-heroku
# http://localhost:8000/api/health; run the frontend with `npm run dev` in frontend/
```
