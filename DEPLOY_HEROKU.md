# Deploying AstroSlide to Heroku

One dyno runs everything: the root `Dockerfile` builds the frontend and FastAPI serves it next to the API. No add-ons (database, Redis, logging) are needed.

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
heroku open
```

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
| `ASTROSLIDE_MAX_DECODE_MEGAPIXELS` | 16 | 180 | Larger images are refused before decoding (a 25 MP image runs Mineral Moon out of memory) |
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
| `ASTROSLIDE_CORS_ORIGINS` | empty | `*` | Sites allowed to call the API from a browser. The frontend is on the same origin, so none are needed; `*` is for the Vite dev server calling `localhost:8000` |
| `ASTROSLIDE_API_DOCS` | 0 | 1 | `/docs`, `/redoc` and `/openapi.json` |

Every response carries a Content-Security-Policy (only this site's scripts, no framing), `nosniff`, `X-Frame-Options: DENY` and a referrer policy. Check them with `curl -sI https://<app>.herokuapp.com/`.

Outside the app: turn on two-factor authentication for the Heroku account (Account settings → Multi-factor authentication), since anyone with the account can push code to the dyno.

## Limits to know

- **30-second request timeout.** Upload time doesn't count, but processing does. Star removal on a large galaxy image takes ~17–20 s on one CPU, which is close to that limit. Stacking runs as a background job, so it isn't affected.
- **Temporary files.** The disk is wiped whenever the dyno restarts (at least once a day, and on every deploy) or an Eco dyno goes to sleep. Stacking jobs in progress and results not yet downloaded are lost.
- **Memory warnings.** If the logs show `R14 (Memory quota exceeded)`, lower `ASTROSLIDE_MAX_MEGAPIXELS`. `H12 (Request timeout)` means a request needed more than 30 s.

## Test the image locally under dyno limits

```bash
docker build -t astroslide-heroku .
docker run --rm --memory=512m --memory-swap=512m --cpus=1 -e PORT=5000 -p 5000:5000 astroslide-heroku
# http://localhost:5000
```
