# NexusOps — Full Deployment Guide
## Fedora Linux · Vercel · Supabase · GitHub

---

## OVERVIEW

```
nexusops/
├── frontend/          → Deploy to Vercel (static site)
│   ├── index.html
│   └── vercel.json
├── backend/           → Deploy to Vercel (Python serverless)
│   ├── main.py
│   ├── requirements.txt
│   ├── vercel.json
│   ├── schema.sql
│   └── .env.example
├── docs/
│   └── email-copy-deck.md
└── .gitignore
```

---

## STEP 1 — Install Tools on Fedora

```bash
# Install Node.js (needed for Vercel CLI)
sudo dnf install -y nodejs npm

# Install Vercel CLI globally
npm install -g vercel

# Install Python + pip (you probably have this already)
sudo dnf install -y python3 python3-pip

# Install Git (if not already)
sudo dnf install -y git

# Verify everything
node --version    # should be 18+
vercel --version
python3 --version # should be 3.11+
git --version
```

---

## STEP 2 — Set Up Supabase

1. Go to https://supabase.com and create a free account
2. Create a new project — name it `nexusops`
3. Wait for it to provision (~2 min)
4. Go to **SQL Editor** → **New Query**
5. Paste the entire contents of `backend/schema.sql` and hit Run
6. Go to **Settings** → **API**
7. Copy these two values (you'll need them shortly):
   - **Project URL** (looks like: `https://abcxyz.supabase.co`)
   - **service_role key** (NOT the anon key — the service role key)

> ⚠️ NEVER put the service_role key in your frontend or commit it to git.
> It bypasses Row Level Security. Backend only.

---

## STEP 3 — Set Up GitHub Repo

```bash
# Navigate to your project
cd ~/nexusops   # or wherever you cloned/built this

# Initialize git
git init
git add .
git commit -m "feat: initial nexusops launch"

# Create repo on GitHub (install gh CLI first if you don't have it)
sudo dnf install -y gh
gh auth login   # follow the browser prompts

# Create the repo and push
gh repo create nexusops --public --push --source=.

# Verify it's live
gh repo view --web
```

---

## STEP 4 — Deploy Backend to Vercel

```bash
cd backend/

# Copy env template and fill in your real values
cp .env.example .env
nano .env
# Fill in:
#   SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
#   SUPABASE_SERVICE_KEY=your-service-role-key
#   ENVIRONMENT=production
#   ALLOWED_ORIGINS=https://nexusops.vercel.app

# Log into Vercel
vercel login

# Deploy (follow the prompts — create new project, name it nexusops-backend)
vercel deploy --prod

# Note the deployment URL — looks like: https://nexusops-backend-xxxx.vercel.app
# You'll need this for the frontend config

# Set environment variables in Vercel (NEVER commit .env)
vercel env add SUPABASE_URL
# Paste your Supabase URL when prompted, select all environments

vercel env add SUPABASE_SERVICE_KEY
# Paste your service role key when prompted

vercel env add ENVIRONMENT
# Type: production

vercel env add ALLOWED_ORIGINS
# Type: https://nexusops.vercel.app (your frontend URL)

# Redeploy with env vars applied
vercel deploy --prod
```

---

## STEP 5 — Update Frontend Config

Open `frontend/index.html` and replace these placeholders:

```
1. API_BASE = "https://YOUR_BACKEND_URL.vercel.app"
   → Replace with your actual backend Vercel URL from Step 4

2. https://calendly.com/YOUR_USERNAME/30min
   → Replace with your actual Calendly link (see Step 6)

3. In vercel.json, update the CSP header:
   connect-src 'self' https://YOUR_BACKEND_URL.vercel.app
   → Replace with your actual backend URL
```

---

## STEP 6 — Set Up Calendly

1. Go to https://calendly.com and create a free account
2. Create a new **Event Type** → "30 Minute Audit Call"
3. Set your availability (recommend: Mon-Fri, 9am-5pm your timezone)
4. Copy your event link: `https://calendly.com/YOUR_USERNAME/30min`
5. Replace `YOUR_USERNAME` everywhere in `index.html`
6. Optional: Connect your Google Calendar for automatic conflict detection

---

## STEP 7 — Deploy Frontend to Vercel

```bash
cd ../frontend/

# Deploy
vercel deploy --prod

# Follow prompts:
# - Project name: nexusops (or nexusops-frontend)
# - Root directory: ./
# - No build command needed (static HTML)
# - Output directory: ./

# Note your frontend URL — update ALLOWED_ORIGINS in backend env vars
```

---

## STEP 8 — Connect Custom Domain (Optional but recommended)

```bash
# In your frontend deployment
vercel domains add nexusops.com
vercel domains add www.nexusops.com

# Vercel will give you DNS records to add
# Log into your domain registrar (Namecheap, GoDaddy, etc.)
# Add the A/CNAME records Vercel provides
# SSL is automatic via Let's Encrypt
```

---

## STEP 9 — Set Up Email (Recommended: Resend)

1. Go to https://resend.com (free tier: 3000 emails/month)
2. Create account, add your domain, verify DNS
3. Get your API key
4. Add to backend env vars:
   ```bash
   vercel env add RESEND_API_KEY
   ```
5. Add this to `backend/main.py` in the waitlist endpoint:
   ```python
   import resend
   resend.api_key = os.environ["RESEND_API_KEY"]
   
   # After successful DB insert:
   resend.Emails.send({
     "from": "NexusOps <hello@nexusops.com>",
     "to": entry.email,
     "subject": "You're on the list. Here's what happens next.",
     "text": "..."  # paste Email 1 from the copy deck
   })
   ```

---

## STEP 10 — Verify Everything Works

```bash
# Test health endpoint
curl https://YOUR_BACKEND_URL.vercel.app/health

# Test waitlist submission
curl -X POST https://YOUR_BACKEND_URL.vercel.app/api/waitlist \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "source": "hero"}'

# Test rate limiting (should 429 after 3 requests)
for i in {1..5}; do
  curl -X POST https://YOUR_BACKEND_URL.vercel.app/api/waitlist \
    -H "Content-Type: application/json" \
    -d "{\"email\": \"test$i@example.com\"}"
done

# Check Supabase dashboard → Table Editor → waitlist
# You should see your test entries
```

---

## MAINTENANCE

### Rotate Supabase Keys (every 90 days)
```bash
# Supabase Dashboard → Settings → API → Regenerate service_role key
# Then update Vercel env:
vercel env rm SUPABASE_SERVICE_KEY
vercel env add SUPABASE_SERVICE_KEY
vercel deploy --prod
```

### View logs
```bash
vercel logs https://YOUR_BACKEND_URL.vercel.app --follow
```

### Push updates
```bash
git add .
git commit -m "feat: your change description"
git push origin main
# Vercel auto-deploys on push if you connected GitHub in the dashboard
```

---

## SECURITY CHECKLIST

Before going live, verify:

- [ ] `.env` is in `.gitignore` and NOT pushed to GitHub
- [ ] Supabase service key is only in Vercel env vars, not in code
- [ ] RLS is enabled on both Supabase tables (schema.sql does this)
- [ ] `ALLOWED_ORIGINS` in backend matches your actual frontend URL
- [ ] Calendly link is your real link (not the placeholder)
- [ ] `API_BASE` in index.html points to your real backend URL
- [ ] Swagger UI is disabled in production (`ENVIRONMENT=production`)
- [ ] Run `curl -I https://YOUR_FRONTEND_URL` and verify security headers are present

---

## COST ESTIMATE (Monthly)

| Service        | Plan       | Cost     |
|----------------|------------|----------|
| Vercel (frontend) | Hobby   | Free     |
| Vercel (backend)  | Hobby   | Free     |
| Supabase          | Free tier | Free    |
| Calendly          | Free tier | Free    |
| Resend (email)    | Free tier | Free    |
| **TOTAL**         |           | **$0/mo** |

You can run this entire stack for free until you're making real money.
Upgrade when you have 10+ clients or 10k+ emails.
