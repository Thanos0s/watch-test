# ✅ Vercel + Render Deployment Checklist

Quick reference for deploying PrakritiDesk to Vercel and Render.

---

## Prerequisites

- [ ] Code pushed to GitHub: https://github.com/Thanos0s/watch-test
- [ ] 
- [ ] Render account created
- [ ] Vercel account created

---

## Backend (Render) - 15 minutes

### Deploy:
- [ ] Go to [render.com](https://render.com) → New Web Service
- [ ] Connect GitHub → Select `watch-test`
- [ ] Root Directory: `intake-engine`
- [ ] Build Command:
  ```
  apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-hin && pip install -r requirements-render.txt
  ```
- [ ] Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### Environment Variables:
- [ ] 
- [ ] `GROQ_MODEL` = `qwen/qwen3.6-27b`
- [ ] `DATABASE_URL` = `sqlite+aiosqlite:///./prakritidesk.db`

### Optional:
- [ ] Add persistent disk (1 GB) at `/opt/render/project/src/data`

### Test:
- [ ] Copy Render URL: `https://prakritidesk-api-xxxx.onrender.com`
- [ ] Visit: `https://prakritidesk-api-xxxx.onrender.com/docs`

---

## Frontend (Vercel) - 5 minutes

### Deploy:
- [ ] Go to [vercel.com](https://vercel.com) → Import Project
- [ ] Select `watch-test` repository
- [ ] Root Directory: `frontend`
- [ ] Framework: Next.js (auto-detected)

### Environment Variables:
- [ ] `NEXT_PUBLIC_API_BASE_URL` = `https://prakritidesk-api-xxxx.onrender.com`
  (Replace with YOUR Render URL!)

### Test:
- [ ] Visit your Vercel URL: `https://watch-test-xxxx.vercel.app`
- [ ] Test doctor dashboard: `https://watch-test-xxxx.vercel.app/doctor`

---

## Verification

- [ ] Kiosk loads
- [ ] API docs accessible  
- [ ] Check-in screen works
- [ ] Doctor dashboard loads
- [ ] HTTPS enabled (automatic)
- [ ] No console errors

---

## Your URLs:

```
Frontend: https://______________________.vercel.app
Backend:  https://______________________.onrender.com
API Docs: https://______________________.onrender.com/docs
```

---

## Need Help?

See detailed guide: **[DEPLOY_VERCEL_RENDER.md](./DEPLOY_VERCEL_RENDER.md)**

---

**Estimated Time**: 20 minutes total  
**Cost**: FREE (with free tiers)
