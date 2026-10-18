# AstroSlide

A web-based astrophotography editor for smart telescope users (Seestar, Dwarf, Vaonis): PixInsight-style results with a simple UI.

## Features

- **Upload** JPEG, PNG, TIFF (8/16-bit) or FITS (mono or color) by drag and drop
- **Presets**: Moon HDR, Mineral Moon, Nebula, with an intensity slider
- **Interactive stretch**: Auto Stretch (PixInsight-style AutoSTF) plus black point / midtones / white point, computed on full bit-depth data; optional star removal
- **Pro Mode**: denoise, star reduction, saturation and sharpening on top of a preset
- **Before/after slider**, live histogram, and export as JPEG, PNG or TIFF

## Project Structure

```
astroslide/
├── backend/     FastAPI + OpenCV/Astropy image processing (main.py, presets.py, tests/)
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

## Deployment

```bash
docker-compose up -d --build
# Frontend: http://localhost
# Backend API: http://localhost:8000
```

For a full server setup, see [DEPLOY_HETZNER.md](DEPLOY_HETZNER.md).

## Technology Stack

- **Frontend**: React, TypeScript, Vite, TanStack Query, Axios, react-compare-image
- **Backend**: FastAPI, OpenCV, Astropy, Pillow, NumPy, scikit-image, PyWavelets

## License

MIT
