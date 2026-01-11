# AstroSlide Quick Start Guide

This guide will help you get AstroSlide up and running on your local machine.

## Prerequisites

Before you begin, ensure you have the following installed:
- Python 3.10 or higher
- Node.js 18 or higher

---

## Local Development Setup

### Step 1: Create Environment File

Create a `.env` file in the project root (optional, defaults are already configured):

```bash
# Backend
BACKEND_PORT=8000

# Frontend
FRONTEND_PORT=5173

# API Configuration
API_BASE_URL=http://localhost:8000
```

### Step 2: Backend Setup

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the backend server:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

The backend API will be available at `http://localhost:8000`

You can view the API documentation at `http://localhost:8000/docs`

### Step 3: Frontend Setup

Open a new terminal window/tab:

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Create a `.env.local` file (optional):
   ```bash
   VITE_API_BASE_URL=http://localhost:8000
   ```

3. Install dependencies:
   ```bash
   npm install
   ```

4. Run the development server:
   ```bash
   npm run dev
   ```

The frontend will be available at `http://localhost:5173`

---

## Using AstroSlide

1. Open your browser and navigate to `http://localhost:5173`

2. You'll see the AstroSlide upload interface

3. Upload an astrophotography image by:
   - Dragging and dropping a file onto the upload zone
   - Clicking the upload zone to select a file

4. Supported formats:
   - JPEG (.jpg, .jpeg)
   - PNG (.png)
   - TIFF (.tiff, .tif)
   - FITS (.fits)
   - Maximum file size: 50MB

5. Wait for the image to be processed (usually 10-30 seconds)

6. Use the before/after slider to compare your original and enhanced images

7. Click "Download Enhanced" to save the processed image

8. Click "Upload New Image" to process another image

---

## Troubleshooting

### Backend Issues

**Problem:** `ModuleNotFoundError` when starting the backend
- **Solution:** Make sure you activated the virtual environment and installed all dependencies

**Problem:** Port 8000 already in use
- **Solution:** Stop any other services using port 8000, or change the port in the uvicorn command

**Problem:** OpenCV errors on Linux
- **Solution:** Install system dependencies:
  ```bash
  sudo apt-get update
  sudo apt-get install libgl1-mesa-glx libglib2.0-0
  ```

### Frontend Issues

**Problem:** `Cannot GET /api/enhance` or CORS errors
- **Solution:** Make sure the backend is running on port 8000. The backend CORS is configured to allow all origins for development.

**Problem:** Port 5173 already in use
- **Solution:** Stop other Vite dev servers, or change the port in `vite.config.ts`

---

## Development Tips

### Hot Reload

Both the backend and frontend support hot reload:
- **Backend:** Changes to Python files will automatically restart the server
- **Frontend:** Changes to React/TypeScript files will automatically update the browser

### API Documentation

The backend automatically generates interactive API documentation:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Testing with Sample Images

For best results, test with:
- Deep sky images (nebulae, galaxies)
- Moon or planetary images
- Star field images

The enhancement pipeline is optimized for astrophotography but will work with any image.

---

## Next Steps

- Read the full [README.md](README.md) for more details
- Check out [prd.md](prd.md) for feature roadmap
- Review [technical-steps.md](technical-steps.md) for architecture details

## Support

If you encounter any issues not covered here, please check the project documentation or open an issue on the repository.

