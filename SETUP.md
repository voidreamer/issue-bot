# Issue Bot — Setup Guide

Mattermost slash command → LLM → GitLab/GitHub issue

## How It Works

```
/issue 3 Build login page with OAuth support
         │
         ▼
   ┌───────────┐     ┌─────────┐     ┌──────────┐
   │ Mattermost│────▶│ FastAPI  │────▶│   LLM    │
   │  /issue   │     │ issue-bot│     │ (OpenAI) │
   └───────────┘     └────┬─────┘     └──────────┘
                          │ structured JSON
                          ▼
                    ┌──────────┐
                    │ GitLab / │  creates issue with
                    │  GitHub  │  title, body, labels, weight
                    └──────────┘
```

### Commands

| Command | Description |
|---|---|
| `/issue <points> <prompt>` | Create an issue (default project) |
| `/issue <project> <points> <prompt>` | Create in a specific project |
| `/issue bug\|feature\|chore <points> <prompt>` | Create with a template |
| `/issue help` | Show available commands and config |
| `/issue list [project]` | List recent open issues |
| `/issue search <query>` | Search issues by text |
| `/issue epic <points> <prompt>` | Create parent + child issues |
| `/issue plan <goals>` | Generate a batch of planned issues |

---

## 1. Get Your Tokens

### GitLab Personal Access Token
1. Go to https://gitlab.com/-/user_settings/personal_access_tokens
2. Create a token with `api` scope
3. Save it — you'll put it in `.env` as `GITLAB_TOKEN`

### Mattermost Slash Command Token
1. In Mattermost, go to **Main Menu → Integrations → Slash Commands**
2. Click **Add Slash Command**:
   - **Command Trigger Word:** `issue`
   - **Request URL:** `https://your-domain.com/bot/slash/issue`
   - **Request Method:** POST
   - **Autocomplete:** enabled
   - **Autocomplete Hint:** `[project] [template] <points> <description>`
   - **Autocomplete Description:** `Create a GitLab issue from a prompt using AI`
3. Save → copy the **Token** → put it in `.env` as `MM_SLASH_TOKEN`

### LLM API Key
- **OpenAI:** https://platform.openai.com/api-keys
- **Anthropic:** https://console.anthropic.com/settings/keys
- **Ollama:** no key needed, just set `LLM_BASE_URL=http://localhost:11434/v1/chat/completions`
- **Gemini:** https://aistudio.google.com/apikey

---

## 2. Deploy

### Option A: Docker (Recommended)

```bash
# Clone/upload the project files
git clone <repo-url> issue-bot
cd issue-bot

# Create your .env file
cp .env.example .env
nano .env  # fill in your tokens

# Build and run
docker compose up -d

# Check health
curl http://localhost:8321/health
```

To update:
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Option B: Bare Metal (GCE/VPS)

SSH into your instance and run:

```bash
# Upload the project files
scp -r ./* your-instance:/tmp/issue-bot/

# On the server
cd /tmp/issue-bot
chmod +x deploy.sh
./deploy.sh
```

Then create the `.env` file:

```bash
sudo nano /opt/issue-bot/.env
```

Paste your values (see `.env.example`), then start:

```bash
sudo systemctl enable --now issue-bot
sudo systemctl status issue-bot    # should show "active (running)"
```

---

## 3. Nginx Reverse Proxy

**Option A — Add to your existing Mattermost nginx config:**

Add this `location` block inside your existing `server` block:

```nginx
location /bot/ {
    proxy_pass http://127.0.0.1:8321/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Then reload: `sudo nginx -t && sudo systemctl reload nginx`

**Option B — Use the provided config:**

```bash
sudo cp nginx-issue-bot.conf /etc/nginx/sites-available/issue-bot
sudo ln -s /etc/nginx/sites-available/issue-bot /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 4. Multi-Project Setup

To manage issues across multiple projects, use `GITLAB_PROJECTS` instead of `GITLAB_PROJECT_ID`:

```env
GITLAB_PROJECTS={"frontend":{"id":"123","name":"Frontend","labels":"bug,feature,enhancement"},"backend":{"id":"456","name":"Backend API","labels":"bug,infra,api"}}
GITLAB_DEFAULT_PROJECT=frontend
```

Each project entry has:
- `id` — GitLab project ID (or `owner/repo` for GitHub)
- `name` — Display name
- `labels` — Comma-separated available labels
- `backend` — `gitlab` (default) or `github`

Then use: `/issue frontend 3 Build login page` or `/issue backend 5 Add auth middleware`

---

## 5. Webhook Notifications

To get notifications in Mattermost when GitLab issues change:

1. Set env vars:
   ```env
   GITLAB_WEBHOOK_SECRET=your-secret
   MM_BOT_TOKEN=your-mattermost-bot-token
   MM_NOTIFY_CHANNEL_ID=channel-id
   ```

2. In GitLab → Settings → Webhooks:
   - **URL:** `https://your-domain.com/bot/webhooks/gitlab`
   - **Secret token:** same as `GITLAB_WEBHOOK_SECRET`
   - **Trigger:** Issue events

3. Create a bot account in Mattermost → Admin → Bot Accounts → get the token

---

## 6. Test It

```bash
# Health check
curl http://localhost:8321/health

# Simulated slash command
curl -X POST http://localhost:8321/slash/issue \
  -d "token=YOUR_MM_TOKEN&user_name=testuser&text=3 Build a voice command parser"

# Help
curl -X POST http://localhost:8321/slash/issue \
  -d "token=YOUR_MM_TOKEN&user_name=testuser&text=help"
```

In Mattermost:
```
/issue 5 Add offline mode with local caching and background sync
/issue bug 3 Login page crashes on Safari
/issue epic 8 Build user authentication system
/issue list
/issue search authentication
```

---

## 7. Switching LLM Providers

Edit your `.env` and change `LLM_PROVIDER`:

| Provider   | `LLM_PROVIDER` | `LLM_MODEL` (default)         | Notes                     |
|------------|-----------------|-------------------------------|---------------------------|
| OpenAI     | `openai`        | `gpt-4o`                      | Best all-round            |
| Anthropic  | `anthropic`     | `claude-sonnet-4-5-20250514`  | Great structured output   |
| Ollama     | `ollama`        | `llama3`                      | Free, runs on your VM     |
| Gemini     | `gemini`        | `gemini-2.0-flash`            | Cheap, fast               |

Then restart: `sudo systemctl restart issue-bot` (or `docker compose restart`)

---

## Troubleshooting

```bash
# View logs (bare metal)
sudo journalctl -u issue-bot -f

# View logs (Docker)
docker compose logs -f

# Test locally
cd /opt/issue-bot
source venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8321 --reload

# Check SQLite database
sqlite3 data/issuebot.db "SELECT * FROM issue_history;"
```
