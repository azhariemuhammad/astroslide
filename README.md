# AstroSlide - Astrophotography Image Editor

A web-based astrophotography image editor that makes post-processing accessible for smart telescope users (Seestar, Dwarf, Vaonis, etc.)

## Features

- **Image Upload**: Support for JPEG, PNG, TIFF, and FITS files with drag-and-drop interface
- **Multiple Enhancement Presets**:
  - 🌙 **Mineral Moon**: Dramatically enhances lunar surface mineral colors
  - 🌌 **Deep Sky Boost**: Optimized for nebulae, galaxies, and star clusters
  - 🪐 **Planet Sharp**: Maximizes detail for planetary imaging
  - ✨ **General Auto**: Balanced enhancement for any astrophoto
- **Before/After Slider**: Interactive comparison slider for instant visual feedback
- **Export**: Download enhanced images at full resolution

### 🌙 New: Mineral Moon Feature

The **Mineral Moon** preset brings out the stunning mineral colors on the lunar surface! This specialized algorithm amplifies the subtle blues, oranges, and yellows that reveal the Moon's geological composition. Perfect for creating dramatic lunar images that showcase titanium-rich maria and iron-rich highlands.

[Learn more about Mineral Moon →](MINERAL_MOON.md)

## Project Structure

```
astroslide/
├── backend/          # FastAPI backend with image processing
├── frontend/         # React frontend with Vite
├── .gitignore
└── README.md
```

## Quick Start

See [QUICKSTART.md](QUICKSTART.md) for detailed setup instructions.

### TL;DR - Local Development

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

### Access Points

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for comprehensive deployment instructions.

**Quick Links:**
- [Docker Deployment](DEPLOYMENT.md#docker-deployment-recommended)
- [Hetzner Cloud Server Guide](DEPLOY_HETZNER.md)
- [Other Cloud Platforms](DEPLOYMENT.md#cloud-platform-deployment)

### Quick Docker Deployment

```bash
# Build and start all services
docker-compose up -d --build

# Access the application
# Frontend: http://localhost
# Backend API: http://localhost:8000
```

## Technology Stack

- **Frontend**: React, TypeScript, Vite, Axios, react-compare-image
- **Backend**: FastAPI, OpenCV, Astropy, Pillow, NumPy, scikit-image

## License

MIT

