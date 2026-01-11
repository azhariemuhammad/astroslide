# Deploying AstroSlide to Hetzner Cloud

This guide walks you through deploying AstroSlide to a Hetzner Cloud Server (VPS) using Docker Compose.

## Prerequisites

- A Hetzner Cloud account (sign up at https://www.hetzner.com/cloud)
- A domain name (optional, but recommended for production)
- Basic familiarity with SSH and Linux commands

## Step 1: Create a Hetzner Cloud Server

1. **Log in to Hetzner Cloud Console** (https://console.hetzner.cloud) and click "Add Server"

2. **Choose configuration:**
   - **Image**: Ubuntu 22.04 (or latest LTS)
   - **Type**: CX11 (1 vCPU, 2 GB RAM) minimum, or CPX11 (2 vCPU, 2 GB RAM) recommended
   - **Location**: Choose closest to your users (Falkenstein, Nuremberg, or Helsinki)
   - **SSH Keys**: Add your SSH key (recommended) or use root password
   - **Networks**: Default (or create a private network if needed)
   - **Firewalls**: Can be configured later
   - **Name**: `astroslide` (or your preferred name)

3. **Click "Create & Buy Now"** and wait for the server to be ready

4. **Note your server's IP address** (you'll need this)

## Step 2: Connect to Your Server

```bash
# Replace YOUR_IP_ADDRESS with your server's IP
ssh root@YOUR_IP_ADDRESS

# Or if using a non-root user:
ssh your_username@YOUR_IP_ADDRESS
```

## Step 3: Initial Server Setup

### Update the system

```bash
apt update && apt upgrade -y
```

### Create a non-root user (recommended)

```bash
# Create user
adduser astroslide
usermod -aG sudo astroslide

# Switch to the new user
su - astroslide
```

### Install Docker and Docker Compose

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group (to run docker without sudo)
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Log out and back in for group changes to take effect
exit
# Then SSH back in
```

### Verify installation

```bash
docker --version
docker compose version
```

## Step 4: Deploy Your Application

### Option A: Clone from Git (Recommended)

```bash
# Install git if not already installed
sudo apt install git -y

# Clone your repository
git clone https://github.com/YOUR_USERNAME/astroslide.git
# Or use your repository URL
cd astroslide
```

### Option B: Upload Files via SCP

From your local machine:

```bash
# From your local machine, navigate to the project directory
cd /path/to/astroslide

# Upload files to the server
scp -r . astroslide@YOUR_IP_ADDRESS:/home/astroslide/astroslide
```

Then on the server:

```bash
cd ~/astroslide
```

## Step 5: Configure Firewall

Hetzner Cloud has a built-in firewall system. You can configure it via the web console or using `ufw`:

### Option A: Using Hetzner Cloud Console (Recommended)

1. Go to your server in Hetzner Cloud Console
2. Click on "Firewalls" tab
3. Create a new firewall or edit existing one:
   - Allow SSH (port 22)
   - Allow HTTP (port 80)
   - Allow HTTPS (port 443)
   - Allow backend port (port 8000, optional)

### Option B: Using UFW (Alternative)

```bash
# Allow SSH
sudo ufw allow OpenSSH

# Allow HTTP (port 80)
sudo ufw allow 80/tcp

# Allow HTTPS (port 443) - for later SSL setup
sudo ufw allow 443/tcp

# Allow backend port (optional, if you want direct access)
sudo ufw allow 8000/tcp

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status
```

## Step 6: Run the Application

```bash
# Navigate to project directory
cd ~/astroslide

# Build and start containers
docker compose up -d --build

# Check if containers are running
docker compose ps

# View logs
docker compose logs -f
```

Your application should now be accessible at:
- **Frontend**: http://YOUR_IP_ADDRESS:3000
- **Backend API**: http://YOUR_IP_ADDRESS:8000
- **API Docs**: http://YOUR_IP_ADDRESS:8000/docs

## Step 7: Set Up Domain Name (Optional but Recommended)

### 7.1 Configure DNS

1. Go to your domain registrar (Namecheap, GoDaddy, etc.)
2. Add an A record:
   - **Type**: A
   - **Host**: @ (or www)
   - **Value**: YOUR_IP_ADDRESS
   - **TTL**: 3600 (or default)

3. Wait for DNS propagation (can take a few minutes to 48 hours)

### 7.2 Update Docker Compose for Domain

If you want to use port 80 instead of 3000, update `docker-compose.yml`:

```yaml
frontend:
  ports:
    - "80:80"  # Change from "3000:80" to "80:80"
```

Then restart:

```bash
docker compose up -d --build
```

## Step 8: Set Up SSL/HTTPS with Let's Encrypt

### 8.1 Install Certbot

```bash
sudo apt install certbot python3-certbot-nginx -y
```

### 8.2 Install Nginx (as reverse proxy)

```bash
sudo apt install nginx -y
```

### 8.3 Create Nginx Configuration

Create `/etc/nginx/sites-available/astroslide`:

```bash
sudo nano /etc/nginx/sites-available/astroslide
```

Add this configuration:

```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    # Proxy to Docker frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # Proxy API requests to backend
    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        client_max_body_size 50M;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/astroslide /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 8.4 Get SSL Certificate

```bash
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

Follow the prompts. Certbot will automatically configure HTTPS.

### 8.5 Auto-renewal

Certbot sets up auto-renewal automatically. Test it:

```bash
sudo certbot renew --dry-run
```

## Step 9: Set Up Auto-Start on Reboot

Docker Compose services should auto-start, but let's ensure it:

### Option A: Docker Compose Restart Policy (Already Set)

The `restart: unless-stopped` in `docker-compose.yml` should handle this.

### Option B: Systemd Service (More Control)

Create `/etc/systemd/system/astroslide.service`:

```bash
sudo nano /etc/systemd/system/astroslide.service
```

Add:

```ini
[Unit]
Description=AstroSlide Application
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/astroslide/astroslide
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0
User=astroslide
Group=docker

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable astroslide
sudo systemctl start astroslide
```

## Step 10: Monitoring and Maintenance

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f frontend
```

### Restart Services

```bash
# Restart all
docker compose restart

# Restart specific service
docker compose restart backend
```

### Update Application

```bash
cd ~/astroslide

# Pull latest changes (if using git)
git pull

# Rebuild and restart
docker compose up -d --build
```

### Check Resource Usage

```bash
# Docker stats
docker stats

# Disk usage
df -h
docker system df
```

## Troubleshooting

### Containers won't start

```bash
# Check logs
docker compose logs

# Check if ports are in use
sudo netstat -tulpn | grep :3000
sudo netstat -tulpn | grep :8000

# Rebuild from scratch
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Can't access from browser

1. **Check firewall:**
   - In Hetzner Cloud Console, verify firewall rules
   - Or check UFW: `sudo ufw status`

2. **Check if containers are running:**
   ```bash
   docker compose ps
   ```

3. **Check if services are listening:**
   ```bash
   curl http://localhost:3000
   curl http://localhost:8000/api/health
   ```

### Out of disk space

```bash
# Clean up Docker
docker system prune -a

# Remove unused images
docker image prune -a
```

### Update failed

```bash
# Stop containers
docker compose down

# Remove old images
docker compose rm -f

# Rebuild
docker compose up -d --build
```

## Security Best Practices

1. **Keep system updated:**
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **Use SSH keys instead of passwords**

3. **Disable root login** (edit `/etc/ssh/sshd_config`):
   ```
   PermitRootLogin no
   ```
   Then restart SSH: `sudo systemctl restart sshd`

4. **Set up fail2ban** (protect against brute force):
   ```bash
   sudo apt install fail2ban -y
   sudo systemctl enable fail2ban
   sudo systemctl start fail2ban
   ```

5. **Regular backups** of your application code and data
   - Use Hetzner Cloud snapshots for easy backups
   - Or set up automated backup scripts

6. **Monitor logs** regularly for suspicious activity

## Cost Optimization

- **Use smaller servers** (CX11) for development/testing
- **Enable Hetzner Cloud monitoring** to track resource usage
- **Set up alerts** for high CPU/memory usage
- **Use snapshots** before major changes (available in Hetzner Cloud Console)
- **Consider Hetzner's pricing**: Very competitive, especially for European users

## Quick Reference Commands

```bash
# Start application
cd ~/astroslide && docker compose up -d

# Stop application
docker compose down

# View logs
docker compose logs -f

# Restart
docker compose restart

# Update
git pull && docker compose up -d --build

# Check status
docker compose ps

# Access container shell
docker compose exec backend bash
docker compose exec frontend sh
```

## Next Steps

- Set up automated backups (Hetzner Cloud snapshots)
- Configure monitoring (e.g., Hetzner Cloud monitoring, UptimeRobot)
- Set up CI/CD pipeline for automatic deployments
- Configure email notifications for errors
- Set up log aggregation (optional)

---

**Need Help?**
- Check the main [DEPLOYMENT.md](DEPLOYMENT.md) for general deployment info
- Hetzner Cloud Documentation: https://docs.hetzner.com/
- Docker Documentation: https://docs.docker.com/

