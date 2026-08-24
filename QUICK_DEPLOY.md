# ⚡ Quick Deploy Guide

## 🚀 Choose Your Deployment

### 1️⃣ Local Development (5 minutes)

```bash
# Backend
cd intake-engine
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # Add GROQ_API_KEY
uvicorn app.main:app --reload --port 8001

# Frontend (new terminal)
cd frontend
npm install
npm run dev

# Access at:
# http://localhost:3000 (Kiosk)
# http://localhost:3000/doctor (Dashboard)
# http://127.0.0.1:8001/docs (API)
```

---

### 2️⃣ Docker (Production) - 3 minutes

```bash
# 1. Create .env
cat > .env << EOF
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=llama-3.1-8b-instant
EOF

# 2. Deploy
docker compose up --build -d

# 3. Check
docker compose ps
docker compose logs -f

# Access at:
# http://localhost:8001 (API)
# http://localhost:8001/docs (API Docs)
```

---

### 3️⃣ Cloud (Vercel + Render) - 15 minutes

**Backend (Render.com)**:
1. Sign up at render.com
2. New Web Service → Connect GitHub
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add env vars: `GROQ_API_KEY`, `DATABASE_URL`
6. Deploy → Copy URL

**Frontend (Vercel.com)**:
1. Sign up at vercel.com
2. Import Project → Connect GitHub
3. Root: `frontend`
4. Add env: `NEXT_PUBLIC_API_BASE_URL=https://your-render-url.com`
5. Deploy → Add custom domain (HTTPS required for Bluetooth)

---

### 4️⃣ Kiosk/Edge Device - 20 minutes

```bash
# Ubuntu setup
sudo apt update
curl -fsSL https://get.docker.com | sh
sudo apt install docker-compose

# Deploy
git clone <repo>
cd PrakritiDesk-main
nano .env  # Add GROQ_API_KEY
docker compose up -d

# Kiosk mode
sudo apt install chromium-browser
chromium-browser --kiosk --enable-features=WebBluetooth \
  http://localhost:3000
```

---

## 🔑 Required Environment Variables

```bash
# .env file (backend)
GROQ_API_KEY=gsk_...          # Get free at console.groq.com
GROQ_MODEL=llama-3.1-8b-instant
DATABASE_URL=sqlite+aiosqlite:////app/data/prakritidesk.db

# Optional
BHASHINI_USER_ID=...          # For Hindi voice
BHASHINI_API_KEY=...
```

```bash
# .env.local file (frontend)
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001
```

---

## ✅ Post-Deployment Checklist

- [ ] API health check: `curl http://your-url:8001/`
- [ ] API docs accessible: `http://your-url:8001/docs`
- [ ] Frontend loads: `http://your-url:3000`
- [ ] HTTPS enabled (required for Bluetooth in production)
- [ ] Run tests: `pytest` (backend), `npm test` (frontend)
- [ ] Check logs: `docker compose logs -f`
- [ ] Backup setup: Schedule database backups

---

## 🚨 Common Issues

| Problem | Solution |
|---------|----------|
| Port 8001 in use | Change in `docker-compose.yml` or kill process |
| Backend won't start | Check `GROQ_API_KEY` in `.env` |
| Frontend can't connect | Update `NEXT_PUBLIC_API_BASE_URL` |
| Bluetooth not working | Use Chrome/Edge + HTTPS |
| Docker errors | `docker compose down -v && docker compose up --build` |

---

## 📚 Full Documentation

- **Complete Guide**: [DEPLOYMENT.md](./DEPLOYMENT.md)
- **Testing**: [TESTING.md](./TESTING.md)
- **Bluetooth**: [HOW_TO_CONNECT_SMARTWATCH.md](./frontend/HOW_TO_CONNECT_SMARTWATCH.md)
- **Main README**: [README.md](./README.md)

---

## 🎯 Recommended Deployment by Use Case

| Use Case | Recommended Option |
|----------|-------------------|
| **Development** | Local (Python + npm) |
| **Demo/Prototype** | Docker |
| **Production Web** | Cloud (Vercel + Render) |
| **Hospital Kiosk** | Edge Docker on Ubuntu |
| **Enterprise** | AWS/Azure with RDS |

---

## 🆘 Quick Help

```bash
# Check backend health
curl http://localhost:8001/

# View backend logs
docker compose logs -f intake-engine

# Restart services
docker compose restart

# Update deployment
git pull
docker compose up --build -d

# Backup database
docker compose cp intake-engine:/app/data/prakritidesk.db ./backup/
```

---

**Need detailed instructions?** See [DEPLOYMENT.md](./DEPLOYMENT.md)

**Ready to deploy?** Choose an option above and follow the steps! 🚀
