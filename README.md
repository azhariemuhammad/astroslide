# AstroSlide

A web-based astrophotography editor for smart telescope users (Seestar, Dwarf, Vaonis): PixInsight-style results with a simple UI.

## Features

- **Upload** JPEG, PNG, TIFF (8/16-bit) or FITS (mono or color) by drag and drop
- **Moon video stacking** (lucky imaging): drop one or more Seestar clips (RAW `.avi` or `.mp4`) from the same night; the sharpest frames are aligned (field rotation, seeing wobble) and averaged into a 16-bit image that opens in the editor
- **Presets**: Mineral Moon (with Deblur, Sharpen, HDR and Halo sliders) and Nebula (with an intensity slider)
- **Interactive stretch**: Auto Stretch (PixInsight-style AutoSTF) plus black point / midtones / white point, computed on full bit-depth data; optional star removal
- **Pro Mode**: denoise, star reduction, saturation and sharpening on top of a preset
- **Before/after slider**, live histogram, and export as JPEG, PNG or TIFF

## Project Structure

```
astroslide/
├── backend/     FastAPI + OpenCV/Astropy image processing (main.py, presets.py, stacking.py, tests/)
├── frontend/    React + Vite editor
└── samples/     Real test images (FITS files are gitignored; keep them local)
```

## Local Development

**Backend:**
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend (in a new terminal):**
```bash
cd frontend
npm install
npm run dev
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000 (docs at http://localhost:8000/docs)

## Testing

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest                          # fast unit tests
python tests/regression.py --update       # record golden-image baselines (once, before a change)
python tests/regression.py                # compare against baselines after a change
```

The regression run processes a fixed set of inputs (`samples/` plus synthetic linear FITS) through every preset and stretch, then writes `tests/regression_data/report.html` showing baseline vs. current side by side for anything that changed. Real samples missing from `samples/` are skipped.

## Video Stacking

The stacker also runs from the command line:

```bash
cd backend
python stacking.py clip1.avi clip2.avi -o stack.fits --keep 0.7
```

RAW `.avi` (8-bit Bayer, linear) is saved as 16-bit FITS and `.mp4` as 16-bit PNG. In the app, stacking is a background job (`POST /api/stack`, then poll `GET /api/stack/{id}`); job folders live in `ASTROSLIDE_JOBS_DIR` (default: the system temp dir) and expire after two hours. Uploads are limited to `ASTROSLIDE_MAX_STACK_GB` (default 6). A raw clip is about 1 GB per minute, so on a remote server the upload takes longer than the stacking.

## Deployment

```bash
docker-compose up -d --build
# Frontend: http://localhost
# Backend API: http://localhost:8000
```

For a full server setup, see [DEPLOY_HETZNER.md](DEPLOY_HETZNER.md). For a single $5–7/month Heroku dyno (frontend served by FastAPI, sized for 512 MB), see [DEPLOY_HEROKU.md](DEPLOY_HEROKU.md).

## Technology Stack

- **Frontend**: React, TypeScript, Vite, TanStack Query, Axios, react-compare-image
- **Backend**: FastAPI, OpenCV, Astropy, Pillow, NumPy, scikit-image, PyWavelets

## License

MIT
