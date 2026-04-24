# Montana Premium House Care — Slack Bot Setup & Deployment Guide (v4)

**Business:** Montana Premium House Care
**Owner:** Chris Johnson
**Office Manager:** Carolyn Donaldson
**Phone:** 406-599-2699 (business) | 406-599-2699 (scheduling)
**Email:** mtpremiumhousecare@gmail.com
**Service Areas:** Bozeman, Gallatin County, Livingston, Belgrade, Big Sky, Kalispell, Whitefish

---

## What This Bot Does

Slack is Carolyn's **single pane of glass** — she never needs to leave Slack. The bot proactively monitors HousecallPro, texts, leads, and messages, then alerts Carolyn when something needs attention and helps her get it done.

### 10 Slash Commands (Under Slack's 25 Limit)

| Command | Module | Subcommands |
|---|---|---|
| `/leads` | Lead Tools | `find` `status` `inbox` `summary` |
| `/job` | Job Management | `assign` `list` `checkin` `checkout` |
| `/customer` | Customer Comms | `new` `followup` `complete` |
| `/hcp` | HousecallPro | `jobs` `customers` `leads` `analysis` |
| `/ai` | AI-Powered Tools | `draft` `complaint` `recommend` `status` |
| `/service` | Customer Service | `script` `standards` `qa` `wow` |
| `/office` | Carolyn's Command Center | `brief` `priorities` `feed` `eod` `text` `reply` `profit` `payrate` `status` |
| `/carolyn` | Profile & Wellness | `meet` `answer` `profile` `update` `mood` |
| `/announce` | Team Broadcast | *(direct message)* |
| `/cleanhelp` | Help | *(shows all commands)* |

### v4 New Features

- **Unified Feed** — All events (leads, texts, HCP messages, alerts) in one stream via `/office feed`
- **Smart Alerts** — Bot proactively pings Carolyn when leads go unresponded, texts are missed, or jobs need confirmation
- **Quick Reply** — Reply to texts and HCP messages directly from Slack via `/office reply`
- **Twilio SMS** — Send and receive texts from the business line (406-599-2699) inside Slack
- **HCP Message Monitor** — Customer texts from the scheduling line appear in Slack automatically
- **End-of-Day Summary** — Auto-posts at 5pm: what got done, what's open, what's tomorrow
- **Employee Profitability** — Pulls HCP timesheets and calculates profit margins per employee
- **Pay Rate Management** — Set and track hourly rates per employee

---

## Step 1 — Register Slash Commands in Slack

Go to [api.slack.com/apps](https://api.slack.com/apps) → Select your app → **Slash Commands** → Create each:

> Since the bot uses **Socket Mode**, leave the Request URL blank or enter any placeholder.

| # | Command | Description | Usage Hint |
|---|---|---|---|
| 1 | `/leads` | Lead tools: find, status, inbox, summary | `[subcommand] [args]` |
| 2 | `/job` | Job management: assign, list, checkin, checkout | `[subcommand] [args]` |
| 3 | `/customer` | Customer comms: new, followup, complete | `[subcommand] [args]` |
| 4 | `/hcp` | HousecallPro: jobs, customers, leads, analysis | `[subcommand] [args]` |
| 5 | `/ai` | AI tools: draft, complaint, recommend, status | `[subcommand] [args]` |
| 6 | `/service` | Customer service: script, standards, qa, wow | `[subcommand] [args]` |
| 7 | `/office` | Command center: brief, priorities, feed, eod, text, reply, profit, payrate, status | `[subcommand] [args]` |
| 8 | `/carolyn` | Profile & wellness: meet, answer, profile, update, mood | `[subcommand] [args]` |
| 9 | `/announce` | Team broadcast message | `Your message here` |
| 10 | `/cleanhelp` | Show all commands | *(none)* |

---

## Step 2 — Configure Your .env File

Open the `.env` file and fill in your credentials:

### Already Set
- `SLACK_BOT_TOKEN` — Your bot token
- `SLACK_SIGNING_SECRET` — Your signing secret
- `SLACK_APP_TOKEN` — Your app-level token
- Business info (name, phone, email, service areas)

### HousecallPro (MAX Plan Required)
1. Log into HousecallPro at [app.housecallpro.com](https://app.housecallpro.com)
2. Go to **Settings → App Store** → Find **API** → Click **Generate API Key**
3. Copy the key and paste into `.env`: `HOUSECALLPRO_API_KEY=your_key_here`

### OpenAI API Key (Required for AI Features)
1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create a new API key
3. Set `OPENAI_API_KEY=your_key_here`

### Claude AI (Optional — Premium Customer Service Writing)
1. Go to [console.anthropic.com](https://console.anthropic.com) → Create an API key
2. Set `ANTHROPIC_API_KEY=your_key_here`

### Mailchimp (Optional)
1. Log into Mailchimp → Account → Extras → API Keys → Create Key
2. Set `MAILCHIMP_API_KEY=` and `MAILCHIMP_LIST_ID=`

### Twilio SMS (For Business Phone 406-599-2699)
1. Sign up at [twilio.com/try-twilio](https://www.twilio.com/try-twilio)
2. Port 406-599-2699 from AT&T to Twilio (see Twilio Porting Guide below)
3. Set `TWILIO_ACCOUNT_SID=`, `TWILIO_AUTH_TOKEN=`, `TWILIO_PHONE_NUMBER=+14065992699`
4. In Twilio Console, set the SMS webhook URL to: `https://your-server.com:5050/sms`
5. Set call forwarding in Twilio to forward to your HCP VOIP number

### Employee Pay Rates
Set each employee's hourly rate in the `.env` file:
```
EMPLOYEE_PAY_RATES=Sarah:18,Mike:16.50,Jane:17,Tom:15
DEFAULT_HOURLY_RATE=17.00
```
Or set them at runtime via `/office payrate Sarah 19.50`

---

## Step 3 — Run Locally

```bash
cd cleanbiz_bot
pip install -r requirements.txt
python bot.py
```

You should see:
```
🧹 Montana Premium House Care Slack Bot (v4 — Command Center Edition) starting...
📍 Service areas: Bozeman, Gallatin County, Livingston, Belgrade, Big Sky, Kalispell, Whitefish
🔑 HousecallPro API: ✅
🤖 gpt-4.1-mini: ✅ Active
🤖 gemini-2.5-flash: ✅ Active
📱 Twilio SMS: ✅ Active
🔄 Lead monitor polling started (every 15 min)
🔄 Command center started (smart alerts + HCP message monitor)
⚡️ Bot is running!
```

---

## Step 4 — Deploy to Cloud (24/7 Operation)

### Option A: Railway (Recommended — $5/month)

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Push your bot code to a GitHub repo:
   ```bash
   cd cleanbiz_bot
   git init
   git add .
   git commit -m "Montana Premium House Care bot v4"
   git remote add origin https://github.com/YOUR_USERNAME/mtpremium-bot.git
   git push -u origin main
   ```
3. Click **New Project** → **Deploy from GitHub Repo** → Select your repo
4. Go to **Variables** tab and add ALL your `.env` variables
5. Railway auto-detects the `Procfile` and deploys

### Option B: Render (Free Tier Available)

1. Go to [render.com](https://render.com) and sign in
2. Click **New** → **Background Worker**
3. Connect your GitHub repo
4. Set **Build Command:** `pip install -r requirements.txt`
5. Set **Start Command:** `python bot.py`
6. Add all `.env` variables in the Environment tab

---

## Step 5 — Twilio Porting Guide (406-599-2699 from AT&T)

1. Log into your Twilio Console
2. Go to **Phone Numbers** → **Port & Host** → **Port a Number**
3. Enter `406-599-2699`
4. Provide your AT&T account number and PIN
5. Upload a copy of your AT&T bill
6. Twilio will process the port (takes 1-3 business days)
7. Once ported, configure:
   - **SMS Webhook:** `https://your-server.com:5050/sms` (POST)
   - **Voice:** Forward to your HCP VOIP number
8. Update `.env` with your Twilio credentials and restart the bot

---

## Step 6 — Create Slack Channels

| Channel | Purpose |
|---|---|
| `#leads` | New leads from all platforms auto-posted here |
| `#jobs` | Job assignments and check-in/out updates |
| `#team` | Employee announcements and communications |
| `#customers` | Customer follow-ups, texts, and completion notices |
| `#analytics` | Daily briefs, HCP analysis, profitability reports |
| `#carolyn` | Carolyn's private workspace for drafts and priorities |
| `#alerts` | Smart alerts — unresponded leads, missed texts, job confirmations |

---

## File Structure

```
cleanbiz_bot/
├── bot.py                      # Main bot — all 10 modules, 10 slash commands
├── ai_engine.py                # Multi-model AI (GPT-4.1, Gemini, Claude-ready)
├── customer_service.py         # Chick-fil-A level service standards & scripts
├── carolyn_profile.py          # Carolyn's preferences & onboarding interview
├── lead_monitor.py             # Polls HCP + Mailchimp for leads (every 15 min)
├── command_center.py           # Unified feed, smart alerts, HCP messages, EOD summary
├── twilio_sms.py               # Twilio SMS send/receive + Slack integration
├── employee_profitability.py   # Employee profit margins from HCP job data
├── webhook_server.py           # Receives push leads (Angi webhooks)
├── .env                        # All credentials and configuration
├── .gitignore                  # Excludes .env from version control
├── requirements.txt            # Python dependencies
├── Procfile                    # Cloud deployment process file
├── railway.toml                # Railway-specific config
└── runtime.txt                 # Python version for cloud platforms
```

---

## Quick Reference — All Commands

### Lead Tools
```
/leads find residential bozeman
/leads find airbnb big sky
/leads find post_construction kalispell
/leads find carpet_window all
/leads status
/leads inbox
/leads summary
```

### Job Management
```
/job assign @sarah | 456 Oak St, Bozeman | Deep Clean | Friday 9am
/job list assigned
/job checkin JOB-0001
/job checkout JOB-0001
```

### Customer Communications
```
/customer new Jane Smith | 406-555-1234 | jane@email.com | 456 Oak St | Recurring
/customer followup Jane Smith | 406-555-1234 | Deep Clean
/customer complete Jane Smith | 456 Oak St | Deep Clean | Sarah
```

### HousecallPro
```
/hcp jobs scheduled
/hcp customers Jane Smith
/hcp leads
/hcp analysis
```

### AI-Powered Tools
```
/ai draft airbnb_pitch Sarah
/ai draft estimate_followup John
/ai draft win_back Mike
/ai complaint John Missed a bathroom during deep clean
/ai recommend growth
/ai status
```

### Customer Service
```
/service script new_inquiry
/service standards
/service qa deep_clean
/service wow Sarah
```

### Carolyn's Command Center
```
/office brief                          — AI morning briefing
/office priorities                     — Ranked action items
/office feed                           — Unified event feed (all sources)
/office feed lead                      — Filter: leads only
/office feed text                      — Filter: texts only
/office feed hcp_message               — Filter: HCP messages only
/office eod                            — End-of-day summary
/office text send 4065551234 Hello!    — Send text from business line
/office text inbox                     — View incoming texts
/office text convo 4065551234          — View conversation with a number
/office reply sms 4065551234 Thanks!   — Quick reply to a text
/office reply hcp conv_123 Got it!     — Quick reply to HCP message
/office profit                         — Employee profitability (this week)
/office profit last                    — Employee profitability (last week)
/office payrate                        — View all employee pay rates
/office payrate Sarah 19.50            — Set Sarah's hourly rate
/office status                         — System status overview
```

### Carolyn's Profile
```
/carolyn meet                          — Start onboarding interview
/carolyn answer I prefer warm emails   — Answer interview question
/carolyn profile                       — View saved preferences
/carolyn update email_tone warm        — Update a preference
/carolyn mood great Ready to go!       — Daily mood check-in
```

### Team & Help
```
/announce Team — check your schedules for next week by EOD today.
/cleanhelp
```

---

## Smart Alerts (Automatic — No Commands Needed)

The bot proactively monitors and alerts Carolyn in `#alerts`:

| Alert | Trigger | Why It Matters |
|---|---|---|
| Unresponded Lead | HCP lead sits 30+ min without response | Leads go cold fast — respond within 5 min for best conversion |
| Missed Text | Business line text unanswered 15+ min | Customers expect fast replies |
| Job Confirmation | Job scheduled tomorrow, not confirmed | Prevents no-shows and last-minute cancellations |
| Expiring Estimate | HCP estimate about to expire | Revenue at risk — follow up before it's too late |
| HCP Message | New customer message in HCP | Don't miss customer communications |

---

## Employee Profitability Report

The `/office profit` command generates a detailed report showing:

- **Jobs completed** per employee for the week
- **Hours worked** (calculated from HCP job appointment times)
- **Revenue generated** per employee
- **Tips earned** per employee
- **Labor cost** (hours × hourly rate)
- **Gross profit** and **profit margin** per employee
- **Revenue per hour** — how much each employee generates
- **Efficiency flags** — who's fast, on pace, or slow compared to team average
- **AI insights** — who deserves a raise, who needs coaching, who customers love

### Setting Pay Rates

**Option 1 — In .env file:**
```
EMPLOYEE_PAY_RATES=Sarah:18,Mike:16.50,Jane:17,Tom:15
DEFAULT_HOURLY_RATE=17.00
```

**Option 2 — At runtime via Slack:**
```
/office payrate Sarah 19.50
/office payrate Mike 17.00
```

---

*Montana Premium House Care — Built April 2026 — v4 (Command Center Edition)*
