# 🚀 Deploy PrakritiDesk to Vercel + Render

Complete step-by-step guide to deploy PrakritiDesk with:
- **Frontend** on Vercel (Next.js)
- **Backend** on Render (FastAPI)

**Total Time**: 15-20 minutes  
**Cost**: FREE (with free tiers)

---

## 📋 Prerequisites

Before you start:

- [ ] GitHub account
- [ ] Code pushed to GitHub: https://github.com/Thanos0s/watch-test
- [ ] Groq API key ready
- [ ] Vercel account (sign up at [vercel.com](https://vercel.com))
- [ ] Render account (sign up at [render.com](https://render.com))

---

## 🎯 Deployment Overview

```
┌─────────────────┐
│   GitHub Repo   │
│ watch-test      │
└────┬────────┬───┘
     │        │
     │        └───────────────┐
     │                        │
     ▼                        ▼
┌──────────────┐      ┌──────────────┐
│   Vercel     │      │   Render     │
│  (Frontend)  │◄────►│  (Backend)   │
│  Next.js     │      │  FastAPI     │
└──────────────┘      └──────────────┘
     │                        │
     ▼                        ▼
  Port 3000              Port 8001
```

---

## Part 1: Deploy Backend to Render (15 minutes)

### Step 1: Create Render Account

1. Go to [render.com](https://render.com)
2. Click **"Get Started for Free"**
3. Sign up with GitHub (recommended for easy deployment)

### Step 2: Connect GitHub Repository

1. After logging in, click **"New +"** → **"Web Service"**
2. Click **"Connect account"** to link your GitHub
3. Find and select: **`watch-test`**
4. Click **"Connect"**

### Step 3: Configure Web Service

Fill in the deployment settings:

#### Basic Settings:
```
Name: prakritidesk-api
Region: Oregon (US West)
Branch: main
Root Directory: intake-engine
Runtime: Python 3
```

#### Build & Deploy Settings:
```
Build Command:
apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-hin && pip install -r requirements-render.txt

Start Command:
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

#### Instance Type:
```
Plan: Free (512 MB RAM, enough for testing)
```

### Step 4: Add Environment Variables

Click **"Advanced"** → **"Add Environment Variable"**

Add these variables one by one:

```bash
GROQ_MODEL = qwen/qwen3.6-27b

# Optional but recommended
GROQ_VISION_MODEL = llama-3.2-11b-vision-instruct
DATABASE_URL = sqlite+aiosqlite:///./prakritidesk.db
TESSERACT_CMD = /usr/bin/tesseract
TESSERACT_LANG = eng+hin

# Optional: Bhashini (if you have keys)
BHASHINI_USER_ID = (leave empty for now)
BHASHINI_API_KEY = (leave empty for now)
BHASHINI_PIPELINE_ID = 64392f96daac500b55c543cd

# Optional: ABDM (if you have credentials)
ABDM_CLIENT_ID = (leave empty)
ABDM_CLIENT_SECRET = (leave empty)
```

### Step 5: Add Persistent Disk (Optional but Recommended)

For SQLite database persistence:

1. Scroll to **"Disk"** section
2. Click **"Add Disk"**
3. Configure:
   ```
   Name: prakritidesk-data
   Mount Path: /opt/render/project/src/data
   Size: 1 GB (free tier)
   ```

### Step 6: Deploy!

1. Click **"Create Web Service"**
2. Wait for deployment (10-15 minutes first time)
3. Watch the logs for progress

### Step 7: Verify Backend Deployment

Once deployed, you'll see:
```
Your service is live 🎉
https://prakritidesk-api-xxxx.onrender.com
```

**Test it**:
```bash
# Health check
curl https://prakritidesk-api-xxxx.onrender.com/

# API docs
# Open in browser: https://prakritidesk-api-xxxx.onrender.com/docs
```

**IMPORTANT**: Copy your Render URL! You'll need it for Vercel.

Example: `https://prakritidesk-api-xxxx.onrender.com`

---

## Part 2: Deploy Frontend to Vercel (5 minutes)

### Step 1: Create Vercel Account

1. Go to [vercel.com](https://vercel.com)
2. Click **"Sign Up"**
3. Sign up with GitHub (recommended)

### Step 2: Import Project

1. Click **"Add New..."** → **"Project"**
2. Click **"Import"** next to your **`watch-test`** repository
3. If you don't see it, click **"Adjust GitHub App Permissions"**

### Step 3: Configure Project

#### Framework Settings:
```
Framework Preset: Next.js
Root Directory: frontend
Build Command: npm run build (auto-detected)
Output Directory: .next (auto-detected)
Install Command: npm install (auto-detected)
```

#### Environment Variables:

Click **"Environment Variables"** and add:

```bash
# Replace with YOUR Render backend URL from Part 1
NEXT_PUBLIC_API_BASE_URL = https://prakritidesk-api-xxxx.onrender.com
```

**IMPORTANT**: Replace `prakritidesk-api-xxxx.onrender.com` with your actual Render URL!

### Step 4: Deploy!

1. Click **"Deploy"**
2. Wait 2-3 minutes
3. Vercel will build and deploy automatically

### Step 5: Verify Frontend Deployment

Once deployed, you'll see:
```
🎉 Your project is live!
https://watch-test-xxxx.vercel.app
```

**Test it**:

1. Open: `https://watch-test-xxxx.vercel.app`
2. You should see the PrakritiDesk kiosk interface
3. Test doctor dashboard: `https://watch-test-xxxx.vercel.app/doctor`

---

## 🎉 Deployment Complete!

### Your Live URLs:

```
Frontend (Vercel):
https://watch-test-xxxx.vercel.app

Backend API (Render):
https://prakritidesk-api-xxxx.onrender.com

API Documentation:
https://prakritidesk-api-xxxx.onrender.com/docs
```

---

## ✅ Post-Deployment Checklist

### Test All Features:

- [ ] **Kiosk loads**: Visit your Vercel URL
- [ ] **API responds**: Visit `/docs` on your Render URL
- [ ] **Check-in works**: Try entering ABHA ID
- [ ] **Vitals screen loads**: After consent
- [ ] **Doctor dashboard**: Visit `/doctor` route
- [ ] **Bluetooth ready**: Use Chrome/Edge to test smartwatch pairing

### Common Issues to Check:

- [ ] Backend logs on Render (if API calls fail)
- [ ] Environment variables are correct
- [ ] CORS is configured (should work by default)
- [ ] HTTPS is enabled (required for Web Bluetooth)

---

## 🔧 Troubleshooting

### Backend Issues (Render)

**Problem**: Service won't start

**Solution**:
1. Check Render logs: Dashboard → Your Service → **"Logs"** tab
2. Common issues:
   - Missing environment variable (GROQ_API_KEY)
   - Build command failed (Python version?)
   - Port not binding (make sure using `$PORT`)

**Problem**: API returns 500 errors

**Solution**:
```bash
# Check logs in Render dashboard
# Look for Python tracebacks
# Verify GROQ_API_KEY is set correctly
```

**Problem**: Database errors

**Solution**:
```bash
# Check if disk is mounted
# Verify DATABASE_URL points to /opt/render/project/src/data/
```

### Frontend Issues (Vercel)

**Problem**: "Failed to load resource" errors

**Solution**:
1. Check browser console
2. Verify `NEXT_PUBLIC_API_BASE_URL` is set correctly
3. Make sure it has `https://` prefix
4. No trailing slash at the end

**Problem**: Web Bluetooth not working

**Solution**:
- Vercel automatically provides HTTPS ✅
- Use Chrome or Edge browser
- Check: `chrome://flags/#enable-web-bluetooth`

**Problem**: 404 on `/doctor` route

**Solution**:
- Vercel should auto-detect Next.js routes
- Try redeploying: Vercel Dashboard → Deployments → **"Redeploy"**

---

## 🔄 Update Deployment

### Update Backend (Render):

1. Push code to GitHub: `git push origin main`
2. Render auto-deploys from `main` branch
3. Watch progress in Render logs

### Update Frontend (Vercel):

1. Push code to GitHub: `git push origin main`
2. Vercel auto-deploys from `main` branch
3. Takes 2-3 minutes

### Manual Redeploy:

**Render**:
- Dashboard → Your Service → **"Manual Deploy"** → **"Deploy latest commit"**

**Vercel**:
- Dashboard → Your Project → Deployments → **"Redeploy"**

---

## 📊 Monitoring

### Render Dashboard:

- **Metrics**: CPU, Memory, Response times
- **Logs**: Real-time application logs
- **Events**: Deployment history

### Vercel Dashboard:

- **Analytics**: Page views, performance
- **Logs**: Build and runtime logs
- **Deployments**: History and previews

---

## 💰 Cost & Limits

### Render Free Tier:

- ✅ 750 hours/month (good for single app)
- ✅ 512 MB RAM
- ✅ 1 GB persistent disk
- ⚠️ Spins down after 15 min inactivity (first request slower)
- ⚠️ May have cold starts

### Vercel Free Tier:

- ✅ Unlimited deployments
- ✅ 100 GB bandwidth/month
- ✅ Automatic HTTPS
- ✅ Global CDN
- ✅ No cold starts

### Upgrade Options:

**Render**: $7/month for always-on, 512 MB  
**Vercel**: $20/month for Pro features

---

## 🔐 Security Reminders

### Environment Variables:

- ✅ Never commit API keys to Git
- ✅ Set them in Render/Vercel dashboards
- ✅ Rotate keys periodically

### Database:

- ✅ Use persistent disk on Render
- ✅ Set up regular backups (manual for free tier)
- ✅ For production, consider PostgreSQL

### HTTPS:

- ✅ Both Vercel and Render provide free SSL
- ✅ Required for Web Bluetooth API
- ✅ Automatic certificate renewal

---

## 🎯 Next Steps

### Improve Your Deployment:

1. **Add Custom Domain**:
   - Vercel: Project Settings → Domains
   - Render: Dashboard → Settings → Custom Domain

2. **Set Up Monitoring**:
   - Vercel Analytics (built-in)
   - Sentry for error tracking
   - Render metrics dashboard

3. **Enable CI/CD**:
   - Already automatic with GitHub!
   - Add GitHub Actions for tests before deploy

4. **Database Backup**:
   - Download SQLite from Render disk manually
   - Or upgrade to managed PostgreSQL

5. **Performance**:
   - Upgrade Render to paid tier (no cold starts)
   - Enable Vercel Speed Insights
   - Add caching for API calls

---

## 📞 Support

### Render Support:

- Docs: [render.com/docs](https://render.com/docs)
- Community: [community.render.com](https://community.render.com)
- Status: [status.render.com](https://status.render.com)

### Vercel Support:

- Docs: [vercel.com/docs](https://vercel.com/docs)
- Community: [github.com/vercel/next.js/discussions](https://github.com/vercel/next.js/discussions)
- Status: [vercel-status.com](https://vercel-status.com)

---

## 🎊 Success Checklist

- [ ] Backend deployed on Render
- [ ] Frontend deployed on Vercel
- [ ] API endpoints working
- [ ] Environment variables set
- [ ] Custom domains configured (optional)
- [ ] HTTPS enabled (automatic)
- [ ] Web Bluetooth ready
- [ ] Monitoring set up
- [ ] Team notified of URLs

---

**Congratulations! Your PrakritiDesk is now live! 🚀**

Share your URLs:
- Kiosk: `https://your-app.vercel.app`
- Doctor Dashboard: `https://your-app.vercel.app/doctor`
- API Docs: `https://your-api.onrender.com/docs`

---

*Last updated: August 24, 2026*  
*For detailed deployment options, see [DEPLOYMENT.md](./DEPLOYMENT.md)*
