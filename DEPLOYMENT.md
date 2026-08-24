# 🚀 PrakritiDesk Deployment Guide

Complete guide for deploying PrakritiDesk in various environments: local development, production servers, cloud platforms, and edge/kiosk devices.

---

## 📋 Table of Contents

1. [Deployment Options Overview](#deployment-options-overview)
2. [Prerequisites](#prerequisites)
3. [Local Development](#local-development)
4. [Docker Deployment (Recommended)](#docker-deployment-recommended)
5. [Cloud Deployment](#cloud-deployment)
6. [Edge/Kiosk Deployment](#edgekiosk-deployment)
7. [Production Checklist](#production-checklist)
8. [Environment Variables](#environment-variables)
9. [Troubleshooting](#troubleshooting)

---

## 🎯 Deployment Options Overview

| Option | Best For | Complexity | Cost |
|--------|----------|------------|------|
| **Local Dev** | Development, testing | Low | Free |
| **Docker** | Single server, edge devices | Medium | Low |
| **Cloud (Vercel + Render)** | Scalable web apps | Medium | Free-Paid |
| **Cloud (AWS/Azure/GCP)** | Enterprise, healthcare | High | Paid |
| **Kiosk Edge** | Hospital/clinic kiosks | Medium | Low-Medium |

---

## ✅ Prerequisites

### Required for All Deployments:

1. **API Keys**:
   - Groq API Key (free at [console.groq.com](https://console.groq.com))
   - Optional: Bhashini API keys for Hindi voice support
   - Optional: ABDM credentials for real ABHA gateway

2. **Software** (varies by deployment):
   - Node.js 18+ (for frontend)
   - Python 3.11+ (for backend)
   - Docker & Docker Compose (for containerized deployment)

3. **Browser Requirements** (for Bluetooth):
   - Chrome 56+ or Edge 79+ (for Web Bluetooth support)
   - HTTPS in production (required by Web Bluetooth API)

---

## 💻 Local Development

Best for development, testing, and demos.

### Backend Setup

```bash
# Navigate to backend
cd intake-engine

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create environment file
copy .env.example .env    # Windows
# OR
cp .env.example .env      # macOS/Linux

# Edit .env and add your GROQ_API_KEY
# GROQ_API_KEY=gsk_...

# Run the server
uvicorn app.main:app --reload --port 8001
```

**Backend will be available at**: `http://127.0.0.1:8001`  
**API docs**: `http://127.0.0.1:8001/docs`

### Frontend Setup

```bash
# Navigate to frontend (in a new terminal)
cd frontend

# Install dependencies
npm install

# Create environment file (optional)
# Create .env.local with:
# NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001

# Run development server
npm run dev
```

**Frontend will be available at**: `http://localhost:3000`  
**Kiosk UI**: `http://localhost:3000/`  
**Doctor Dashboard**: `http://localhost:3000/doctor`

### Test the Setup

```bash
# Test backend
curl http://127.0.0.1:8001/

# Run backend tests
cd intake-engine
pytest -v

# Run frontend tests
cd frontend
npm test -- --run
npm run test:e2e
```

---

## 🐳 Docker Deployment (Recommended)

Best for production servers, edge devices, and consistent environments.

### Quick Start

```bash
# 1. Clone repository
git clone <repository-url>
cd PrakritiDesk-main

# 2. Create .env file in project root
cat > .env << EOF
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=llama-3.1-8b-instant
DATABASE_URL=sqlite+aiosqlite:////app/data/prakritidesk.db

# Optional
BHASHINI_USER_ID=your_id
BHASHINI_API_KEY=your_key
BHASHINI_PIPELINE_ID=64392f96daac500b55c543cd

# Optional: ABDM Integration
ABDM_CLIENT_ID=
ABDM_CLIENT_SECRET=
EOF

# 3. Build and run
docker compose up --build -d

# 4. Check status
docker compose ps
docker compose logs -f intake-engine
```

**Backend API**: `http://localhost:8001`  
**API Docs**: `http://localhost:8001/docs`

### Docker with Frontend

Create `docker-compose.frontend.yml`:

```yaml
version: '3.8'

services:
  intake-engine:
    # ... (same as docker-compose.yml)

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    image: prakritidesk/frontend:latest
    container_name: prakritidesk-frontend
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      NEXT_PUBLIC_API_BASE_URL: http://intake-engine:8001
    depends_on:
      - intake-engine
```

Create `frontend/Dockerfile`:

```dockerfile
FROM node:18-alpine AS base

# Install dependencies only when needed
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED 1
RUN npm run build

# Production image
FROM base AS runner
WORKDIR /app
ENV NODE_ENV production
ENV NEXT_TELEMETRY_DISABLED 1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT 3000

CMD ["node", "server.js"]
```

Update `frontend/next.config.mjs`:

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
};

export default nextConfig;
```

Deploy both:

```bash
docker compose -f docker-compose.yml -f docker-compose.frontend.yml up --build -d
```

### Docker Management Commands

```bash
# View logs
docker compose logs -f

# Restart services
docker compose restart

# Stop services
docker compose down

# Update and rebuild
git pull
docker compose up --build -d

# Backup database
docker compose cp intake-engine:/app/data/prakritidesk.db ./backup/

# Restore database
docker compose cp ./backup/prakritidesk.db intake-engine:/app/data/
```

---

## ☁️ Cloud Deployment

### Option 1: Vercel (Frontend) + Render (Backend)

**Best for**: Quick deployment, scalability, free tier available

#### Backend on Render

1. **Sign up** at [render.com](https://render.com)

2. **Create new Web Service**:
   - Connect your GitHub repository
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Instance Type: Free or Starter ($7/month)

3. **Add Environment Variables**:
   ```
   GROQ_API_KEY=gsk_...
   GROQ_MODEL=llama-3.1-8b-instant
   DATABASE_URL=sqlite+aiosqlite:////app/data/prakritidesk.db
   PYTHON_VERSION=3.11
   ```

4. **Add Persistent Disk** (optional, for SQLite):
   - Name: `prakritidesk-data`
   - Mount Path: `/app/data`
   - Size: 1GB

5. **Deploy** and note the URL (e.g., `https://prakritidesk-api.onrender.com`)

#### Frontend on Vercel

1. **Sign up** at [vercel.com](https://vercel.com)

2. **Import Project**:
   - Connect GitHub repository
   - Root Directory: `frontend`
   - Framework: Next.js

3. **Add Environment Variables**:
   ```
   NEXT_PUBLIC_API_BASE_URL=https://prakritidesk-api.onrender.com
   ```

4. **Deploy**

5. **Important**: Add custom domain with HTTPS for Web Bluetooth to work

### Option 2: AWS (Full Stack)

**Components needed**:
- EC2 instance (t3.medium or larger)
- RDS PostgreSQL (optional, for production database)
- S3 (for file uploads)
- CloudFront (for HTTPS/CDN)
- Route 53 (for domain)

**Basic Setup**:

```bash
# 1. Launch EC2 instance (Ubuntu 22.04)
# 2. SSH into instance
ssh -i your-key.pem ubuntu@your-instance-ip

# 3. Install Docker
sudo apt update
sudo apt install -y docker.io docker-compose
sudo usermod -aG docker ubuntu

# 4. Clone repository
git clone <your-repo>
cd PrakritiDesk-main

# 5. Create .env file
nano .env
# Add your environment variables

# 6. Deploy with Docker
docker compose up -d

# 7. Set up Nginx reverse proxy with SSL
sudo apt install -y nginx certbot python3-certbot-nginx

# Create Nginx config
sudo nano /etc/nginx/sites-available/prakritidesk

# Add configuration (see below)

# Enable site
sudo ln -s /etc/nginx/sites-available/prakritidesk /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# 8. Get SSL certificate
sudo certbot --nginx -d your-domain.com
```

**Nginx Configuration** (`/etc/nginx/sites-available/prakritidesk`):

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /api/ {
        proxy_pass http://localhost:8001/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

### Option 3: Azure App Service

```bash
# 1. Install Azure CLI
# https://docs.microsoft.com/en-us/cli/azure/install-azure-cli

# 2. Login
az login

# 3. Create resource group
az group create --name prakritidesk-rg --location eastus

# 4. Deploy backend
az webapp up --name prakritidesk-api \
  --resource-group prakritidesk-rg \
  --runtime "PYTHON:3.11" \
  --plan prakritidesk-plan \
  --sku B1

# 5. Configure environment variables
az webapp config appsettings set \
  --resource-group prakritidesk-rg \
  --name prakritidesk-api \
  --settings GROQ_API_KEY=gsk_...

# 6. Deploy frontend (similar process)
```

---

## 🏥 Edge/Kiosk Deployment

Best for hospital/clinic kiosks with local processing.

### Kiosk Hardware Requirements

**Minimum Specs**:
- CPU: Dual-core 2GHz+
- RAM: 4GB
- Storage: 32GB SSD
- OS: Ubuntu 22.04 LTS or Windows 10/11
- Network: WiFi or Ethernet
- Bluetooth: BLE 4.0+ (for smartwatch pairing)
- Display: Touchscreen (1920x1080 recommended)

**Recommended**: Raspberry Pi 4 (8GB), Intel NUC, or dedicated kiosk PC

### Setup on Ubuntu

```bash
# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# 3. Install Docker Compose
sudo apt install docker-compose

# 4. Clone and deploy
git clone <your-repo>
cd PrakritiDesk-main
nano .env  # Add your API keys
docker compose up -d

# 5. Auto-start on boot
sudo systemctl enable docker

# 6. Set up kiosk browser mode (Chrome)
sudo apt install chromium-browser unclutter

# Create kiosk startup script
cat > ~/start-kiosk.sh << 'EOF'
#!/bin/bash
xset s off
xset -dpms
xset s noblank
unclutter -idle 0 &
chromium-browser --kiosk --noerrdialogs --disable-infobars \
  --enable-features=WebBluetooth \
  http://localhost:3000
EOF

chmod +x ~/start-kiosk.sh

# Add to autostart
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/kiosk.desktop << EOF
[Desktop Entry]
Type=Application
Name=PrakritiDesk Kiosk
Exec=/home/$USER/start-kiosk.sh
EOF
```

### Setup on Windows Kiosk

1. **Install Docker Desktop**: Download from [docker.com](https://docker.com)

2. **Deploy Application**:
   ```cmd
   cd C:\PrakritiDesk-main
   docker compose up -d
   ```

3. **Configure Kiosk Mode**:
   - Install Chrome
   - Create `start-kiosk.bat`:
     ```batch
     @echo off
     "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
       --kiosk ^
       --noerrdialogs ^
       --disable-infobars ^
       --enable-features=WebBluetooth ^
       http://localhost:3000
     ```
   - Add to Windows Startup folder
   - Configure Windows for kiosk mode (Settings → Accounts → Other users → Set up kiosk)

### Offline Mode (Optional)

For clinics with unreliable internet, set up local LLM:

```yaml
# In .env
LOCAL_LLM_ENABLED=true
LOCAL_LLM_BASE_URL=http://localhost:11434
LOCAL_LLM_MODEL=llama3.1:8b

# Install Ollama
# https://ollama.ai/download

# Pull model
ollama pull llama3.1:8b
```

---

## ✅ Production Checklist

### Security

- [ ] Enable HTTPS (required for Web Bluetooth)
- [ ] Set strong database credentials
- [ ] Rotate API keys regularly
- [ ] Set up firewall rules
- [ ] Enable CORS only for known domains
- [ ] Implement rate limiting
- [ ] Regular security updates
- [ ] Backup encryption

### Performance

- [ ] Use production database (PostgreSQL recommended)
- [ ] Enable caching (Redis)
- [ ] Configure CDN for static assets
- [ ] Optimize images
- [ ] Enable gzip compression
- [ ] Monitor resource usage
- [ ] Set up logging
- [ ] Configure alerting

### Compliance (Healthcare)

- [ ] HIPAA compliance review
- [ ] Data encryption at rest
- [ ] Audit logging enabled
- [ ] Access controls configured
- [ ] DPDP consent properly recorded
- [ ] ABDM integration certified (if using real gateway)
- [ ] Backup and disaster recovery plan
- [ ] Incident response plan

### Monitoring

- [ ] Application monitoring (e.g., Sentry)
- [ ] Server monitoring (e.g., Datadog, New Relic)
- [ ] Database monitoring
- [ ] Error tracking
- [ ] Performance metrics
- [ ] Uptime monitoring
- [ ] Log aggregation

---

## 🔧 Environment Variables

### Backend (.env)

```bash
# Required
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama-3.1-8b-instant

# Database
DATABASE_URL=sqlite+aiosqlite:////app/data/prakritidesk.db
# For production PostgreSQL:
# DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname

# Optional: Bhashini (Hindi voice)
BHASHINI_USER_ID=your_bhashini_user_id
BHASHINI_API_KEY=your_bhashini_api_key
BHASHINI_PIPELINE_ID=64392f96daac500b55c543cd

# Optional: ABDM Integration
ABDM_CLIENT_ID=your_abdm_client_id
ABDM_CLIENT_SECRET=your_abdm_client_secret
ABDM_GATEWAY_URL=https://dev.abdm.gov.in/gateway

# Optional: Local LLM Fallback
LOCAL_LLM_ENABLED=false
LOCAL_LLM_BASE_URL=http://localhost:11434
LOCAL_LLM_MODEL=llama3.1:8b

# Optional: Tesseract OCR
TESSERACT_CMD=/usr/bin/tesseract  # Linux
# TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe  # Windows
```

### Frontend (.env.local)

```bash
# API URL (adjust for your deployment)
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001

# For production:
# NEXT_PUBLIC_API_BASE_URL=https://api.your-domain.com
```

---

## 🔍 Troubleshooting

### Backend Issues

**Problem**: "ModuleNotFoundError" when starting backend

```bash
# Solution: Ensure virtual environment is activated
cd intake-engine
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

**Problem**: Database errors

```bash
# Solution: Reset database
rm data/prakritidesk.db
# Restart server - it will recreate tables
```

**Problem**: Groq API errors

```bash
# Check your API key
echo $GROQ_API_KEY

# Test manually
curl -H "Authorization: Bearer $GROQ_API_KEY" \
  https://api.groq.com/openai/v1/models
```

### Frontend Issues

**Problem**: "Cannot connect to backend"

```bash
# Check backend is running
curl http://127.0.0.1:8001/

# Check NEXT_PUBLIC_API_BASE_URL in .env.local
# Make sure it matches your backend URL
```

**Problem**: Web Bluetooth not working

- Ensure using Chrome or Edge browser
- Check HTTPS is enabled (required in production)
- Verify Web Bluetooth is enabled: `chrome://flags/#enable-web-bluetooth`

### Docker Issues

**Problem**: Container fails to start

```bash
# Check logs
docker compose logs -f

# Rebuild from scratch
docker compose down -v
docker compose up --build
```

**Problem**: Port already in use

```bash
# Find process using port
# Windows:
netstat -ano | findstr :8001

# Linux/Mac:
lsof -i :8001

# Kill process or change port in docker-compose.yml
```

### Performance Issues

**Problem**: Slow response times

- Check database size and optimize
- Increase server resources
- Enable caching
- Use production database (PostgreSQL)
- Monitor API rate limits (Groq)

---

## 📞 Support

### Resources

- **Documentation**: See README.md, TESTING.md, HOW_TO_CONNECT_SMARTWATCH.md
- **API Docs**: `http://your-deployment:8001/docs`
- **GitHub Issues**: Report bugs and request features

### Getting Help

1. Check logs: `docker compose logs -f`
2. Review environment variables
3. Test backend API directly: `curl http://localhost:8001/`
4. Check browser console for frontend errors
5. Review this deployment guide

---

## 🎉 Next Steps

After deployment:

1. **Test all features**:
   - Check-in flow (ABHA + OTP)
   - Vitals capture (try smartwatch pairing)
   - Conversational intake
   - Doctor dashboard
   - FHIR export

2. **Set up monitoring**:
   - Application performance
   - Error tracking
   - Uptime monitoring
   - Database backups

3. **Train staff**:
   - Kiosk operation
   - Doctor dashboard usage
   - Troubleshooting basics
   - Emergency procedures

4. **Plan maintenance**:
   - Regular updates
   - Database backups
   - API key rotation
   - Security patches

---

**Deployment Complete!** 🚀

Your PrakritiDesk instance should now be running. Visit your deployment URL and start testing!

*For detailed feature documentation, see the main [README.md](./README.md)*
