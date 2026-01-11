# AstroSlide Deployment Guide

This guide covers multiple deployment options for AstroSlide.

## Table of Contents

1. [Docker Deployment (Recommended)](#docker-deployment)
2. [Manual Deployment](#manual-deployment)
3. [Cloud Platform Deployment](#cloud-platform-deployment)
4. [Environment Variables](#environment-variables)
5. [Production Considerations](#production-considerations)

---

## Docker Deployment (Recommended)

The easiest way to deploy AstroSlide is using Docker Compose.

### Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+

### Quick Start

1. **Clone and navigate to the project:**
   ```bash
   cd astroslide
   ```

2. **Build and start services:**
   ```bash
   docker-compose up -d --build
   ```

3. **Access the application:**
   - Frontend: http://localhost
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

4. **View logs:**
   ```bash
   docker-compose logs -f
   ```

5. **Stop services:**
   ```bash
   docker-compose down
   ```

### Customizing the API URL

If you need to change the backend URL for the frontend, edit `docker-compose.yml`:

```yaml
frontend:
  build:
    args:
      - VITE_API_BASE_URL=http://your-backend-url:8000
```

Then rebuild:
```bash
docker-compose up -d --build frontend
```

---

## Manual Deployment

### Backend Deployment

1. **Install dependencies:**
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Run with uvicorn (production):**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
   ```

3. **Or use a process manager (systemd example):**
   
   Create `/etc/systemd/system/astroslide-backend.service`:
   ```ini
   [Unit]
   Description=AstroSlide Backend API
   After=network.target

   [Service]
   User=www-data
   WorkingDirectory=/path/to/astroslide/backend
   Environment="PATH=/path/to/astroslide/backend/venv/bin"
   ExecStart=/path/to/astroslide/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

   Enable and start:
   ```bash
   sudo systemctl enable astroslide-backend
   sudo systemctl start astroslide-backend
   ```

### Frontend Deployment

1. **Build the frontend:**
   ```bash
   cd frontend
   npm install
   VITE_API_BASE_URL=http://your-backend-url:8000 npm run build
   ```

2. **Serve with nginx:**
   
   Copy the built files:
   ```bash
   sudo cp -r dist/* /usr/share/nginx/html/
   ```

   Update nginx config (usually `/etc/nginx/sites-available/default`):
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       root /usr/share/nginx/html;
       index index.html;

       # SPA routing
       location / {
           try_files $uri $uri/ /index.html;
       }

       # Proxy API requests to backend
       location /api {
           proxy_pass http://localhost:8000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection 'upgrade';
           proxy_set_header Host $host;
           proxy_cache_bypass $http_upgrade;
       }

       # Cache static assets
       location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
           expires 1y;
           add_header Cache-Control "public, immutable";
       }
   }
   ```

   Test and reload nginx:
   ```bash
   sudo nginx -t
   sudo systemctl reload nginx
   ```

---

## Cloud Platform Deployment

### Option 1: Railway

1. **Install Railway CLI:**
   ```bash
   npm i -g @railway/cli
   railway login
   ```

2. **Deploy backend:**
   ```bash
   cd backend
   railway init
   railway up
   ```

3. **Deploy frontend:**
   ```bash
   cd frontend
   railway init
   # Set VITE_API_BASE_URL to your backend URL
   railway variables set VITE_API_BASE_URL=https://your-backend.railway.app
   railway up
   ```

### Option 2: Render

**Backend:**
1. Create a new Web Service
2. Connect your GitHub repository
3. Set:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Environment: Python 3

**Frontend:**
1. Create a new Static Site
2. Connect your GitHub repository
3. Set:
   - Build Command: `cd frontend && npm install && npm run build`
   - Publish Directory: `frontend/dist`
   - Environment Variable: `VITE_API_BASE_URL=https://your-backend.onrender.com`

### Option 3: Hetzner Cloud Server

See [DEPLOY_HETZNER.md](DEPLOY_HETZNER.md) for a complete step-by-step guide to deploying on a Hetzner Cloud Server.

**Quick Summary:**
1. Create Ubuntu 22.04 Cloud Server (2GB RAM minimum)
2. Install Docker and Docker Compose
3. Clone repository and run `docker compose up -d --build`
4. Configure firewall and domain (optional)
5. Set up SSL with Let's Encrypt

### Option 4: AWS (EC2 + S3 + CloudFront)

**Backend on EC2:**
1. Launch EC2 instance (Ubuntu)
2. Install dependencies and run backend
3. Configure security group to allow port 8000

**Frontend:**
1. Build frontend: `VITE_API_BASE_URL=https://your-backend.com npm run build`
2. Upload `dist/` to S3 bucket
3. Configure CloudFront distribution
4. Set up custom domain

### Option 5: Google Cloud Run

**Backend:**
1. Create `Dockerfile` (already included)
2. Build and deploy:
   ```bash
   gcloud builds submit --tag gcr.io/PROJECT-ID/astroslide-backend ./backend
   gcloud run deploy astroslide-backend --image gcr.io/PROJECT-ID/astroslide-backend --platform managed
   ```

**Frontend:**
1. Build with backend URL
2. Deploy to Cloud Storage + Cloud CDN or Firebase Hosting

---

## Environment Variables

### Backend

No environment variables are currently required, but you can add:

- `PORT`: Server port (default: 8000)
- `LOG_LEVEL`: Logging level (default: info)
- `MAX_UPLOAD_SIZE`: Max file size in bytes (default: 50MB)

### Frontend

- `VITE_API_BASE_URL`: Backend API URL (default: `http://localhost:8000`)

   **Important:** This must be set at build time, not runtime!

---

## Production Considerations

### Security

1. **CORS Configuration:**
   Update `backend/main.py` to restrict CORS origins:
   ```python
   allow_origins=["https://your-domain.com"]  # Replace "*"
   ```

2. **Rate Limiting:**
   Consider adding rate limiting to prevent abuse:
   ```bash
   pip install slowapi
   ```

3. **HTTPS:**
   Always use HTTPS in production. Use Let's Encrypt with Certbot:
   ```bash
   sudo certbot --nginx -d your-domain.com
   ```

4. **File Upload Limits:**
   The current limit is 50MB. Adjust in `main.py` if needed.

### Performance

1. **Backend Workers:**
   Use multiple workers for better performance:
   ```bash
   uvicorn main:app --workers 4
   ```

2. **Caching:**
   - Frontend assets are cached for 1 year
   - Consider adding Redis for API response caching

3. **CDN:**
   Use a CDN (CloudFlare, CloudFront) for static assets

### Monitoring

1. **Health Checks:**
   - Backend: `http://your-backend/api/health`
   - Frontend: Check nginx status

2. **Logging:**
   - Backend logs: Check uvicorn output
   - Frontend logs: Check browser console and nginx logs

3. **Error Tracking:**
   Consider integrating Sentry or similar service

### Scaling

- **Horizontal Scaling:** Run multiple backend instances behind a load balancer
- **Database:** If you add user accounts, use PostgreSQL or similar
- **File Storage:** For production, consider S3/GCS for uploaded files

---

## Troubleshooting

### Backend won't start
- Check Python version (3.12+)
- Verify all dependencies are installed
- Check port 8000 is not in use: `lsof -i :8000`

### Frontend can't connect to backend
- Verify `VITE_API_BASE_URL` is set correctly at build time
- Check CORS settings in backend
- Verify backend is accessible from frontend server

### Docker issues
- Check logs: `docker-compose logs`
- Rebuild images: `docker-compose up -d --build`
- Check ports aren't in use

---

## Quick Reference

### Docker Commands
```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# View logs
docker-compose logs -f

# Rebuild
docker-compose up -d --build

# Restart a service
docker-compose restart backend
```

### Manual Deployment Commands
```bash
# Backend
cd backend && source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000

# Frontend build
cd frontend && npm install && npm run build
```

---

For more help, check the main [README.md](README.md) or open an issue.

