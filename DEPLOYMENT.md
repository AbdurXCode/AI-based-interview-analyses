# AWS EC2 deployment guide

This guide walks through deploying **AI Interview Preparation Platform** (Next.js frontend + FastAPI backend + PostgreSQL via NeonDB) on a single **Ubuntu** EC2 instance behind **Nginx**, with optional **HTTPS** via **Let's Encrypt / Certbot** and DNS on **DuckDNS**.

Replace placeholders such as `YOUR_DOMAIN`, `YOUR_REPO_URL`, `YOUR_EC2_PUBLIC_IP`, and paths that match your server layout.

---

## Table of contents

1. [What you will run](#what-you-will-run)
2. [Prerequisites](#prerequisites)
3. [Before deployment: beginner toolkit](#before-deployment-beginner-toolkit-for-first-timers)
4. [1. AWS EC2 and security groups](#1-aws-ec2-and-security-groups)
5. [2. DNS (example: DuckDNS)](#2-dns-example-duckdns)
6. [3. SSH from Windows PowerShell](#3-ssh-from-windows-powershell)
7. [4. Prepare the Ubuntu server](#4-prepare-the-ubuntu-server)
8. [5. Deploy code (Git clone and permissions)](#5-deploy-code-git-clone-and-permissions)
9. [6. Backend: Python, env, migrations](#6-backend-python-env-migrations)
10. [7. Frontend: Node, production build](#7-frontend-node-production-build)
11. [8. systemd services (24/7)](#8-systemd-services-247)
12. [9. Nginx reverse proxy](#9-nginx-reverse-proxy)
13. [10. HTTPS with Certbot](#10-https-with-certbot)
14. [11. Smoke tests](#11-smoke-tests)
15. [12. Updating the app](#12-updating-the-app)
16. [13. Troubleshooting](#13-troubleshooting)

---

## What you will run

| Piece            | Listen (localhost) | Public path                          |
|-----------------|---------------------|--------------------------------------|
| Next.js          | `3000`              | `/` (via Nginx)                      |
| FastAPI          | `8080`              | `/api/v1/...` and `/api/openapi.json` (via Nginx) |
| Nginx            | `80`, `443`         | Reverse proxy + TLS                  |

**Important URLs for this project**

- Frontend API base in the browser comes from **`NEXT_PUBLIC_BACKEND_URL`**. For production this must be your **HTTPS site origin** (no trailing slash), **not** `http://127.0.0.1:8080`.
- Backend must allow browser origins via **`CORS_ORIGINS`** (comma-separated).

---

## Prerequisites

Before starting:

- An **Ubuntu** EC2 instance (recommended: Ubuntu LTS AMI).
- A **PostgreSQL** database reachable from EC2 — this guide assumes **NeonDB** (`DATABASE_URL` with host in Neon, not `localhost`).
- **`GEMINI_API_KEY`** (or whatever your deployment uses — see `.env.example`) on the server in `backend/.env`.
- A Git hosting account and a way to clone private repos (classic **personal access token** recommended instead of password).
- **Optional but recommended**: a hostname (e.g. DuckDNS) pointing at the instance's **Elastic IP** or current public IPv4.

---

## Before deployment: beginner toolkit (for first-timers)

Deployment uses **two environments**:

- **Your Windows PC**: PowerShell, your `.pem` key, browser tests.
- **The EC2 server**: a **Linux shell** (`bash`) logged in as user **`ubuntu`**. Nearly all commands below run **on the server** after SSH.

Typical confusion: copying a command block from Windows into the server terminal is fine. If SSH asks something in the terminal, answers are typed there, not in PowerShell (unless reconnecting).

### Terminal basics (`cd`, folders, prompts)

After SSH you usually see something like:

`ubuntu@ip-xxx:~$`

- **`pwd`** (“print working directory”) shows where you are.
- **`cd /var/www/AI_Interview_Analysis`** moves into that folder. Wrong folder is the #1 cause of “file not found” errors.
- **`ls`** lists files in the current folder (`ls -la` includes hidden files like `.env`).

Linux paths always use **`/`** (not `\`).

### What `sudo` means

Commands starting with **`sudo`** run **as administrator** (“superuser”). The system may ask you for **your ubuntu user password** (the prompt is masked when you type). Use `sudo` when:

- Installing packages (`apt`).
- Editing system files (`/etc/nginx/...`).
- Listening on ports `< 1024` (not needed here; we use **80**/**443** behind Nginx, which starts as root but workers run as configured).

If a command fails with **Permission denied**, try whether it should be run with `sudo`.

### Text editor: `nano` (open, save, exit)

This guide uses **`nano`** for small edits on the server. You do **not** need to learn `vim` for this path.

| Action | Keys / steps |
|--------|----------------|
| **Open or create a file** | `nano /path/to/file` or `nano file-in-current-folder` |
| **Move cursor** | Arrow keys |
| **Search** | `Ctrl+W`, type text, Enter |
| **Cut line** | `Ctrl+K` (optional) |
| **Paste (if cut in nano)** | `Ctrl+U` |
| **Save (“Write Out”)** | `Ctrl+O`, then **Enter** to confirm the filename |
| **Exit** | `Ctrl+X` |
| **Exit with unsaved changes** | `Ctrl+X` → nano asks “Save modified buffer?” → press **`Y`** to save or **`N`** to discard, then confirm filename if saving |
| **Cancel a prompt** | `Ctrl+C` |
| **Help** | `Ctrl+G` (cheat sheet at bottom of screen) |

**“Stuck in nano”:** almost always means you are still inside the editor. Press **`Ctrl+X`**. If it asks to save, choose **`N`** if you want to leave without saving.

**Paste mistakes:** pasting from the web into `nano` can insert odd characters (e.g. `1~`). If Nginx later says **`unknown directive`**, open the file again and delete the garbage line.

**Open at a line number** (useful for big config files):

```bash
sudo nano +25 /etc/nginx/sites-available/interview
```

That opens the file with the cursor near line **25**.

### Two terminal sessions (very common pattern)

Some steps need **one process running** (e.g. `uvicorn`) and **another shell** to run `curl`.

- **Option A:** Open a **second** PowerShell window on Windows and SSH to the same server again.
- **Option B:** Use **`tmux`** on the server to split panes (install in [section 4](#4-prepare-the-ubuntu-server)).

Press **`Ctrl+C`** in the shell where a dev server is running to **stop** it (not the same as closing nano — that is `Ctrl+X` in nano only).

### `systemctl` and `journalctl` (services and logs)

After you move to **systemd** (section 8), you control apps with:

| Command | Meaning |
|---------|---------|
| `sudo systemctl start NAME` | Start now |
| `sudo systemctl stop NAME` | Stop now |
| `sudo systemctl restart NAME` | Stop then start (common after config/code changes) |
| `sudo systemctl status NAME` | Running? recent errors? (press **`q`** to leave the pager) |
| `sudo systemctl enable NAME` | Start automatically on server boot |
| `journalctl -u NAME -f` | **Follow** live logs (stop following with **`Ctrl+C`**) |
| `journalctl -u NAME -n 200 --no-pager` | Last 200 lines, then return to prompt |

**`reload` vs `restart` (Nginx):** after a **valid** config change, `sudo systemctl reload nginx` applies without dropping all connections. If `nginx -t` fails, **do not** reload — fix the file first.

### Quick read of `curl` HTTP codes

Many checks use:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/openapi.json
```

- **`200`** is usually success.
- **`301` / `302`** redirects (common for HTTP → HTTPS).
- **`404`** wrong path or app not serving that route.
- **`502` / `504`** often Nginx cannot talk to backend or timed out.

---

## 1. AWS EC2 and security groups

1. **Launch instance**
   - AMI: **Ubuntu** (LTS).
   - Instance size: choose based on workload (AI workloads benefit from adequate RAM/CPU).
   - Attach or create a **security group** (next step).
   - In the EC2 console, open your instance and copy the **Public IPv4 address** (you will use it as `YOUR_EC2_PUBLIC_IP` in SSH). If you assigned an **Elastic IP**, use that address instead (it stays stable across stop/start if associated).

2. **Security group inbound rules** (minimal for this stack)

   | Type  | Port | Source        | Purpose        |
   |------|------|---------------|----------------|
   | SSH  | 22   | Your IP / VPN | Remote admin   |
   | HTTP | 80   | `0.0.0.0/0`   | Certbot HTTP-01 + redirect |
   | HTTPS| 443  | `0.0.0.0/0`   | Public site    |

   **SSH tip:** Prefer restricting port **22** to your home/office IP ranges instead of `0.0.0.0/0`.

3. **Elastic IP (optional)**  
   If you use DuckDNS or a fixed DNS name, allocating an Elastic IP avoids IP churn when you stop/start the instance.

---

## 2. DNS (example: DuckDNS)

1. Create a DuckDNS subdomain (example: `interviewprepration.duckdns.org`).
2. Set the DuckDNS IP to your instance's **current public IPv4** (or Elastic IP).
3. Wait for propagation; verify from your laptop:

   ```bash
   nslookup YOUR_DOMAIN
   ```

---

## 3. SSH from Windows PowerShell

1. Store your `.pem` key somewhere safe (**never commit keys to Git**). The full path might look like `C:\Users\you\keys\my-key.pem`.

2. **Restrict permissions on the `.pem` file**  
   OpenSSH refuses to use a key that is “too open”. In **PowerShell as your normal user** (run as Administrator usually **not** needed):

   ```powershell
   icacls "C:\path\to\your-key.pem" /inheritance:r
   icacls "C:\path\to\your-key.pem" /grant:r "$($env:USERNAME):(R)"
   ```

   If `ssh` still complains about permissions, move the key under your user folder and retry the `icacls` commands on the new path.

3. **First connection host key prompt**  
   The first time you connect to an IP, SSH prints a message about **authenticity of host** … **Are you sure you want to continue connecting?** — type **`yes`** and Enter.

4. Connect (default Ubuntu user is **`ubuntu`**, not `root` on Ubuntu AMIs):

   ```powershell
   ssh -i "C:\path\to\your-key.pem" ubuntu@YOUR_EC2_PUBLIC_IP
   ```

   You should land in a Linux prompt like `ubuntu@ip-...:~$`. You are now on the server.

5. **Disconnect** when done: type **`exit`** and Enter, or close the window.

---

## 4. Prepare the Ubuntu server

Run updates and install tooling:

```bash
sudo apt update && sudo apt upgrade -y
```

`apt update` refreshes the package list; `upgrade` installs security updates. `-y` skips extra yes/no prompts.

```bash
sudo apt install -y git python3 python3-venv python3-pip nginx \
  build-essential
```

**Install Node.js 18+** (LTS). One common path is **NodeSource**; this example matches **Node 20.x** on Ubuntu—if the script URL 404s on your release, open [NodeSource/setup](https://github.com/nodesource/distributions/blob/master/README.md) and use the current instructions for your Ubuntu version:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

Verify:

```bash
node -v
npm -v
```

Both should print version numbers (no “command not found”).

(Optional) **`tmux`** is useful before **systemd**, so a long `npm run build` keeps running if SSH drops:

```bash
sudo apt install -y tmux
tmux new -s deploy
```

**tmux cheat sheet:**

| Action | Keys |
|--------|------|
| Detach (leave session running) | `Ctrl+B`, then **`d`** |
| List sessions later | `tmux ls` |
| Attach again | `tmux attach -t deploy` |

---

## 5. Deploy code (Git clone and permissions)

### 5.1 Web root and ownership

`/var/www` is often owned by `root`. Create your app folder and give it to **`ubuntu`** so `git clone` works:

```bash
sudo mkdir -p /var/www
sudo mkdir -p /var/www/AI_Interview_Analysis
sudo chown -R ubuntu:ubuntu /var/www/AI_Interview_Analysis

cd /var/www/AI_Interview_Analysis
```

Confirm you are empty or safe to populate:

```bash
pwd
ls -la
```

### 5.2 Clone

Use the **exact** repo URL from your host (avoid typos in the repo name — a wrong name yields "Repository not found").

**HTTPS with a Personal Access Token (PAT) (recommended)**

1. On GitHub: **Settings → Developer settings → Personal access tokens** (fine-grained or classic).
2. Create a token with **read access to repositories** at minimum.
3. On the server, run (replace placeholders):

```bash
git clone https://YOUR_GITHUB_USER@github.com/YOUR_ORG/YOUR_REPO.git .
```

When Git asks for **`Password`**, paste the **token** (GitHub no longer accepts account passwords here). Username is typically your GitHub username; for some setups the username can be **`git`** depending on URL style—use the clone URL Copy button from GitHub to avoid mistakes.

If you prefer not to paste the token into the terminal, search for **Git credential helper** or deploy with **SSH deploy keys** (advanced).

The **`.`** at the end means “clone into the **current** folder” (`/var/www/AI_Interview_Analysis`), not into a new subfolder.

If `git clone` fails with permission errors, revisit **ownership** above before retrying.

---

## 6. Backend: Python, env, migrations

### 6.1 Virtualenv and dependencies

```bash
cd /var/www/AI_Interview_Analysis/backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-api.txt -e .
```

### 6.2 `backend/.env`

Create **`/var/www/AI_Interview_Analysis/backend/.env`** (never commit secrets). Use the repo’s `.env.example` as a checklist.

On the server:

```bash
cd /var/www/AI_Interview_Analysis/backend
nano .env
```

Paste or type your values, then **save** (`Ctrl+O`, Enter) and **exit** (`Ctrl+X`).  
If the file should not exist yet, `nano` creates it on first save.

Generate **`JWT_SECRET`** on the server, then paste the line into **`nano`** with your other vars:

```bash
openssl rand -hex 32
```

Minimal production-oriented example (adjust Neon URL, secrets, and domain):

```env
JWT_SECRET=paste-output-of-openssl-rand-hex-32-here
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@YOUR_NEON_HOST:5432/DBNAME?sslmode=require
GEMINI_API_KEY=your-key

CORS_ORIGINS=https://YOUR_DOMAIN,http://localhost:3000
```

**Neon note:** Ensure the URL matches what your migrations and app actually use (`postgresql+psycopg://` as used in `.env.example`).

### 6.3 Run Alembic with env loaded

**Activate the venv** every new SSH session before `pip` / `alembic` / `uvicorn`:

```bash
cd /var/www/AI_Interview_Analysis/backend
source .venv/bin/activate
```

Your prompt may show `(.venv)` when active.

If `alembic upgrade head` shows **connection refused to localhost**, the app/migrations did not pick up **`DATABASE_URL`**. Export variables from `.env` into this shell:

```bash
set -a && source .env && set +a
alembic upgrade head
```

- **`set -a`** means “automatically export every variable that `source .env` sets.”  
- **`set +a`** turns that off afterward (good habit).

Quick sanity check (still with venv activated and after `source .env` as above):

```bash
python -c "import os; print(os.getenv('DATABASE_URL'))"
```

Expected: prints your Neon connection string (starting with `postgresql+psycopg://`). If it prints **`None`**, `.env` was not sourced or **`DATABASE_URL`** is missing/commented wrongly.

### 6.4 Manual smoke test (optional)

```bash
cd /var/www/AI_Interview_Analysis/backend
source .venv/bin/activate
set -a && source .env && set +a
uvicorn main:app --host 0.0.0.0 --port 8080
```

From **another** SSH session on the server (see **Beginner toolkit → Two terminal sessions** above):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/openapi.json
```

You want a **`200`** (or redirect if you oddly front it with nginx—here direct `8080` should be **200** on `/openapi.json`).

In the first shell where **`uvicorn`** runs, press **`Ctrl+C`** to stop the server. **Production** uses **systemd** (next sections), not manual `uvicorn`, long term.

---

## 7. Frontend: Node, production build

### 7.1 `frontend/.env.production`

Next.js embeds **`NEXT_PUBLIC_*`** variables at **build time**. Set the public backend origin to **your site**:

```bash
cd /var/www/AI_Interview_Analysis/frontend
nano .env.production
```

Create the file if it does not exist; save with **`Ctrl+O`**, exit with **`Ctrl+X`**.

Example:

```env
NEXT_PUBLIC_BACKEND_URL=https://YOUR_DOMAIN
NODE_ENV=production
```

Wrong value (`http://127.0.0.1:8080`) causes **"Cannot reach the API"** in the browser — the browser tries to reach the **user's** loopback, not the server.

### 7.2 Install and build

```bash
cd /var/www/AI_Interview_Analysis/frontend
npm ci || npm install
npm run build
```

### 7.3 Manual smoke test (optional)

```bash
npm run start
```

Verify:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/
```

Stop with `Ctrl+C` when done.

---

## 8. systemd services (24/7)

**systemd** keeps your API and frontend running **in the background** and restarts them if they crash **systemd units** live as root-owned files under `/etc/systemd/system/`. Use **`sudo`** to create/edit them.

### 8.0 Create unit files safely

Easiest pattern: **`sudo nano /path`** (nano as root writes where your user alone cannot).

Backend file path:

```bash
sudo nano /etc/systemd/system/interview-backend.service
```

Paste the block below exactly, adjust paths **only if** your install directory differs. Save (`Ctrl+O`, Enter), exit (`Ctrl+X`). Repeat similarly for the frontend unit.

Then always run **`sudo systemctl daemon-reload`** after creating or editing any `*.service` file.

Run both apps as **`ubuntu`** and **restart on failure**.

### 8.1 Backend unit

`/etc/systemd/system/interview-backend.service`:

```ini
[Unit]
Description=Interview FastAPI backend
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/var/www/AI_Interview_Analysis/backend
EnvironmentFile=/var/www/AI_Interview_Analysis/backend/.env
ExecStart=/var/www/AI_Interview_Analysis/backend/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

**Optional hardening:** For higher concurrency/long requests, swap `uvicorn` for **gunicorn** + uvicorn workers (install `gunicorn` in your venv and adjust `ExecStart`).

Reload systemd, enable (start on boot), start **now**, and check status:

```bash
sudo systemctl daemon-reload
sudo systemctl enable interview-backend
sudo systemctl start interview-backend
sudo systemctl status interview-backend --no-pager
```

- **`active (running)`** in green-ish text is good.  
- If **failed**, read the red lines—often typo in **`ExecStart`** or missing `.venv`.

Follow logs (**stop with Ctrl+C**):

```bash
journalctl -u interview-backend -f --no-pager
```

### 8.2 Frontend unit

Create the file:

```bash
sudo nano /etc/systemd/system/interview-frontend.service
```

`/etc/systemd/system/interview-frontend.service`:

```ini
[Unit]
Description=Interview Next.js frontend
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/var/www/AI_Interview_Analysis/frontend
Environment=NODE_ENV=production
ExecStart=/usr/bin/npm run start -- --hostname 127.0.0.1 --port 3000
Restart=always

[Install]
WantedBy=multi-user.target
```

If `npm` is not under `/usr/bin/npm`, locate it with `command -v npm` **as ubuntu** on the server and update `ExecStart` to match that absolute path:

```bash
command -v npm
```

Reload, enable, start, status (same rhythm as backend):

```bash
sudo systemctl daemon-reload
sudo systemctl enable interview-frontend
sudo systemctl start interview-frontend
sudo systemctl status interview-frontend --no-pager
journalctl -u interview-frontend -f --no-pager
```

### 8.3 Port already in use (`EADDRINUSE` on port 3000)

Example flow:

```bash
sudo ss -lntp | grep ':3000'
```

Read the **`pid=NUMBER`** fragment in the matching line—that **NUMBER** is the PID:

```bash
sudo kill -9 PID_FROM_HERE
sudo systemctl restart interview-frontend
sudo systemctl status interview-frontend --no-pager
```

Avoid `kill -9` unless necessary; here it clears a stuck stray Node when you cannot stop it cleanly.

---

## 9. Nginx reverse proxy

Enable your site conf and proxy:

- **`/` →** `http://127.0.0.1:3000` (Next.js)
- **`/api/` →** `http://127.0.0.1:8080` (FastAPI) with routing rules detailed below.

### 9.1 Site file

Target path:

```bash
sudo nano /etc/nginx/sites-available/interview
```

Paste the chosen config block (HTTP-only **or** HTTPS, see below).

**Sanity checklist before reloading**

1. **`server_name YOUR_DOMAIN`** must match DuckDNS hostname (example: `interviewprepration.duckdns.org`), no typo.
2. **`location /api/v1/`** block must appear **above** the broader **`location /api/`** block (order matters).
3. No stray paste characters (`1~` etc.) anywhere.

Then test config then reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

If `nginx -t` prints **`syntax is ok`** and **`test is successful`**, you are safe to reload.

**First-time TLS flow:** If you do **not** have certificates yet:

1. Use only the **`listen 80`** `server { ... }` block from below that **proxies** `/`, `/api/v1/`, and `/api/`—**omit** both the `return 301`-only server block and the entire **`listen 443`** server block until Certbot creates certs.
2. Reload Nginx (`nginx -t` then `reload`).
3. From your laptop, open **`http://YOUR_DOMAIN/api/openapi.json`** (HTTP, not HTTPS) and confirm JSON or at least not an Nginx **500**.
4. Run **Certbot** (section 10). It can rewrite your nginx file to add SSL, **or** you replace the site file afterward with the full HTTP→HTTPS redirect + **`443`** version below—just ensure certificate paths exist under `/etc/letsencrypt/live/YOUR_DOMAIN/`.

After TLS works, rely on **`https://`** URLs only.

### 9.1a HTTP-only `server { }` block (paste this before you have TLS certificates)

Use this **only** until Certbot succeeds. Replace **`YOUR_DOMAIN`**. It matches the **`location`** rules of the HTTPS version so you behavior-test once, then swap to Certbot-managed SSL or the dual-server example below.

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name YOUR_DOMAIN;

    client_max_body_size 25m;

    location /api/v1/ {
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
        send_timeout 600s;

        proxy_pass http://127.0.0.1:8080;
    }

    location /api/ {
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
        send_timeout 600s;

        rewrite ^/api/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:8080;
    }

    location / {
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_pass http://127.0.0.1:3000;
    }
}
```

Then **`sudo nginx -t && sudo systemctl reload nginx`** and browse **`http://YOUR_DOMAIN/`** (not HTTPS until Certbot runs).

Baseline pattern once HTTPS exists (HTTP redirect + HTTPS):

```nginx
# After Certbot: HTTP redirects to HTTPS; HTTPS terminates TLS and proxies upstream
server {
    listen 80;
    listen [::]:80;
    server_name YOUR_DOMAIN;

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name YOUR_DOMAIN;

    ssl_certificate /etc/letsencrypt/live/YOUR_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/YOUR_DOMAIN/privkey.pem;

    client_max_body_size 25m;

    # Long-running AI/analysis routes — avoids 504 from default proxy timeouts
    location /api/v1/ {
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
        send_timeout 600s;

        proxy_pass http://127.0.0.1:8080;
    }

    location /api/ {
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
        send_timeout 600s;

        # Strip /api for paths like /docs and /openapi.json exposed as /api/openapi.json
        rewrite ^/api/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:8080;
    }

    location / {
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_pass http://127.0.0.1:3000;
    }
}
```

Enable symlink and disable default site if desired:

```bash
sudo ln -sf /etc/nginx/sites-available/interview /etc/nginx/sites-enabled/interview
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t
sudo systemctl reload nginx
```

### 9.2 Config hygiene

- After editing with `nano`, ensure there are **no stray pasted characters** (e.g. `1~`). A bad line causes `nginx: [emerg] unknown directive`.
- Prefer `sudo nano +LINE /etc/nginx/sites-available/interview` to jump near a region you edit.

---

## 10. HTTPS with Certbot

Certbot proves you control **`YOUR_DOMAIN`** using **HTTP-01** checks (needs port **80** reachable from the internet). DNS must resolve to **this EC2**.

Install Certbot and the Nginx plugin (package names vary slightly by Ubuntu version):

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_DOMAIN
```

**Interactive prompts usually include**

- Email (for expiry notices)—use a **real inbox** if you rely on reminders.
- Agree to terms.
- Possibly **Sharing email** with EFF (optional preference).
- **Redirect HTTP to HTTPS** — choose **`2`** redirect when offered (recommended for production).

Certbot installs certificates under `/etc/letsencrypt/live/YOUR_DOMAIN/`.

**If issuance fails:**

- **`Connection refused`** to port 80: security group missing **TCP 80** inbound, Nginx not running, wrong DNS pointing elsewhere.
- **DNS not propagated:** wait and rerun `sudo certbot --nginx -d YOUR_DOMAIN`.

Verify auto-renewal timer:

```bash
sudo systemctl list-timers | grep certbot
```

Dry-run renew (harmless simulation):

```bash
sudo certbot renew --dry-run
```

---

## 11. Smoke tests

From your **local** machine:

```bash
curl -I https://YOUR_DOMAIN/
curl -I https://YOUR_DOMAIN/api/openapi.json
curl -s -o /dev/null -w "%{http_code}\n" https://YOUR_DOMAIN/api/health
```

From the server (loopback):

```bash
sudo ss -lntp | egrep ':80|:443|:3000|:8080'
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/openapi.json
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/
```

Expected:

- **200** class responses for frontend, `/api/openapi.json`, and **`/api/health`** (`/health` on the backend is routed via the **`/api/`** strip rule in Nginx—not under `/api/v1/`).

You can cross-check bypassing nginx on the server:

```bash
curl -s http://127.0.0.1:8080/health
```

Should return JSON like `{"status":"ok"}`.

- **Browser:** login flows work once **`CORS_ORIGINS`** includes your **`https://YOUR_DOMAIN`** and **`NEXT_PUBLIC_BACKEND_URL`** was set **before** `npm run build`.

---

## 12. Updating the app

Typical rollout:

```bash
cd /var/www/AI_Interview_Analysis
git pull

# Backend deps/migrations if needed
cd backend
source .venv/bin/activate
pip install -r requirements-api.txt -e .
set -a && source .env && set +a
alembic upgrade head

# Frontend rebuild if deps or NEXT_PUBLIC_* changed
cd ../frontend
npm ci || npm install
npm run build

sudo systemctl restart interview-backend
sudo systemctl restart interview-frontend
sudo nginx -t && sudo systemctl reload nginx
```

If you changed **`NEXT_PUBLIC_BACKEND_URL`** or any `NEXT_PUBLIC_*` variable: you **must** run **`npm run build`** again before restart.

---

## 13. Troubleshooting

| Symptom | Likely cause | What to check |
|---------|----------------|---------------|
| `Permission denied` on `git clone` in `/var/www` | Ownership | `sudo chown -R ubuntu:ubuntu /var/www/AI_Interview_Analysis` |
| Repository not found | Wrong URL / token scope | Exact clone URL and PAT scopes |
| `alembic` **connection refused** (localhost) | `DATABASE_URL` not loaded | `set -a; source .env; set +a` before Alembic; verify Neon URL host |
| Browser cannot reach API; calls go to **127.0.0.1:8080** | Wrong NEXT_PUBLIC_* at build time | Set `NEXT_PUBLIC_BACKEND_URL`, **rebuild** frontend |
| CORS errors | Backend rejects origin | `CORS_ORIGINS` includes `https://YOUR_DOMAIN` |
| Frontend service fails: **`EADDRINUSE :3000`** | Old Next process running | `ss` + `kill` + `restart` systemd unit |
| **504 Gateway Time-out** on long AI/resume endpoints | Nginx upstream timeout too low | Increase `proxy_*_timeout` and `send_timeout` in `/api/` locations |
| **`unknown directive`** in nginx | Typo/stray chars in site file | `sudo nginx -t`, open file and delete garbage lines |
| Login 404 / wrong API path behind Nginx | `/api/` rewrite strips `/api/v1/` | Ensure **`location /api/v1/` comes before broader `/api/`** and uses bare `proxy_pass http://127.0.0.1:8080;` |

**Logs**

```bash
journalctl -u interview-backend -n 200 --no-pager
journalctl -u interview-frontend -n 200 --no-pager
sudo tail -n 200 /var/log/nginx/error.log
```

Mock interview fallback text such as **"Evaluation service busy"** often indicates transient **LLM quota/timeout/errors** rather than nginx routing — check backend logs around the request time after fixing upstream timeouts.

---

## Security reminders

- Do **not** commit `.pem` keys, `.env`, or production secrets.
- Prefer **least privilege** IAM and tight SSH ingress.
- Rotate **`JWT_SECRET`** and DB credentials if leaked.
- Keep the OS and Python/Node deps updated (`apt`, `pip`, `npm`).

---

_End of deployment guide._
