# Issue Bot — Setup Guide

Mattermost slash command → LLM → GitLab issue

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
                    │  GitLab  │  creates issue with
                    │   API    │  title, body, labels, weight
                    └──────────┘
```

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
   - **Request URL:** `https://mm.guidedgrowthapp.com/bot/slash/issue`
     (adjust if you use a different domain/path for the bot)
   - **Request Method:** POST
   - **Autocomplete:** ✅ enabled
   - **Autocomplete Hint:** `<points> <description>`
   - **Autocomplete Description:** `Create a GitLab issue from a prompt using AI`
3. Save → copy the **Token** → put it in `.env` as `MM_SLASH_TOKEN`

### LLM API Key
- **OpenAI:** https://platform.openai.com/api-keys
- **Anthropic:** https://console.anthropic.com/settings/keys
- **Ollama:** no key needed, just set `LLM_BASE_URL=http://localhost:11434/v1/chat/completions`
- **Gemini:** https://aistudio.google.com/apikey

---

## 2. Deploy on Your GCE Instance

SSH into your instance and run:

```bash
# Upload the project files (from your local machine)
scp -r ./* your-gce-instance:/tmp/issue-bot/

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

## 4. Test It

```bash
# Health check
curl https://mm.guidedgrowthapp.com/bot/health

# Manual test (simulates Mattermost POST)
curl -X POST https://mm.guidedgrowthapp.com/bot/slash/issue \
  -d "token=YOUR_MM_TOKEN&user_name=manuel&text=3 Build a voice command parser for daily habits"
```

Then in Mattermost, type:
```
/issue 5 Add offline mode with local caching and background sync
```

---

## 5. Switching LLM Providers

Edit `/opt/issue-bot/.env` and change `LLM_PROVIDER`:

| Provider   | `LLM_PROVIDER` | `LLM_MODEL` (default)         | Notes                     |
|------------|-----------------|-------------------------------|---------------------------|
| OpenAI     | `openai`        | `gpt-4o`                      | Best all-round            |
| Anthropic  | `anthropic`     | `claude-sonnet-4-5-20250514`  | Great structured output   |
| Ollama     | `ollama`        | `llama3`                      | Free, runs on your VM     |
| Gemini     | `gemini`        | `gemini-2.0-flash`            | Cheap, fast               |

Then restart: `sudo systemctl restart issue-bot`

---

## Troubleshooting

```bash
# View logs
sudo journalctl -u issue-bot -f

# Test locally
cd /opt/issue-bot
source venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8321 --reload
```
