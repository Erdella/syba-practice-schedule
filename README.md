# SYBA North Fargo Practice Scheduler

A web app for scheduling youth basketball practices across the gyms covered
by the Fargo Public Schools contract. WYSIWYG drag-and-drop, gym
double-booking warnings, per-team `.ics` calendar export, and a real backend
so editors share one schedule everyone sees.

**Public visitors** see the schedule in read-only mode — no signup needed.
**Editors** log in and the full WYSIWYG grid appears. Changes auto-save and
sync to other editors in real time.

Built on [PocketBase](https://pocketbase.io) — a single Go binary that bundles
authentication, a SQLite database, an admin UI, and a REST API.

## Repository contents

| File | Purpose |
|------|---------|
| `pb_public/index.html`     | The app. Served at `/` by PocketBase. |
| `pb_migrations/*.js`       | Auto-runs on first boot — creates the `schedules` collection and seeds it. |
| `Dockerfile`               | Builds an Alpine image with the PocketBase binary baked in. |
| `docker-compose.yml`       | Default runner — bind-mounts the HTML and migrations, persists data via the `pb_data` volume. |
| `update.sh`                | Cron-friendly: `git pull` and rebuild the container if something changed. |
| `.gitignore`               | Excludes `pb_data/` (the live database — never commit). |

## First-time deployment on your firewall PC

```bash
# 1. Clone the repo
sudo mkdir -p /opt/syba-scheduler && sudo chown $USER /opt/syba-scheduler
git clone https://github.com/Erdella/syba-practice-schedule.git /opt/syba-scheduler
cd /opt/syba-scheduler

# 2. Build and start
docker compose up -d --build

# 3. Verify the API is responding
curl http://localhost:8090/api/health
# {"code":200,"message":"API is healthy."}
```

### Set up the admin account (one-time)

Open `http://<host-ip>:8090/_/` in a browser. PocketBase will prompt you to
**create the first admin** — pick an email and a strong password you'll
remember. This account manages users and has full data access. Save it
somewhere durable.

The migrations have already created the `schedules` collection with starter
teams and gyms. You should see it in the admin UI under **Collections**.

### Add editor accounts

In the admin UI:

1. Open the **Users** collection (left sidebar).
2. Click **+ New record**.
3. Set **email**, **password**, and **passwordConfirm**. (The other fields
   can stay empty.) Save.
4. Repeat for each person who needs edit access.

Share the email + password with that editor through whatever secure channel
you use. They can change their own password later via PocketBase's account
management endpoints (or you can simply update the password from the admin
UI).

To remove edit access: delete the user from the **Users** collection.

### Use the app

Visit `http://<host-ip>:8090/`. Without logging in, you see the read-only
schedule. Click **🔐 Log in to edit**, enter editor credentials, and the
full WYSIWYG editor takes over.

## Putting it on a public hostname (HTTPS)

The container speaks plain HTTP on port 8090. To expose it as
`schedule.sybafargo.com` with HTTPS, run a reverse proxy in front.

### Caddy (easiest, automatic Let's Encrypt)

`/etc/caddy/Caddyfile`:

```caddy
schedule.sybafargo.com {
    reverse_proxy localhost:8090
}
```

Make sure ports 80 and 443 reach the firewall PC and that DNS for
`schedule.sybafargo.com` points to your public IP. Caddy will pull a TLS
cert automatically.

**Important — realtime sync needs WebSocket support.** Caddy handles this
without configuration. If you use a proxy that doesn't pass WebSockets by
default (older nginx setups), make sure `Connection: upgrade` and
`Upgrade: $http_upgrade` headers are forwarded, otherwise editor changes
won't sync between sessions in real time.

## Updating the app

After commits land on `main` in your GitHub repo:

```bash
cd /opt/syba-scheduler
git pull
docker compose up -d --build
```

The `pb_data/` volume is **not** affected by the rebuild — accounts and
schedule data persist.

### Auto-update via cron

```bash
chmod +x update.sh
crontab -e
# Check for updates every 10 min:
*/10 * * * * cd /opt/syba-scheduler && ./update.sh >> update.log 2>&1
```

`update.sh` only rebuilds the container when the repo actually has new
commits, so it's safe to run frequently.

## Backing up

The whole live state lives in `pb_data/`. To back up:

```bash
# Snapshot while running (PocketBase uses WAL mode, this is safe)
sudo tar czf /backup/syba-pb-$(date +%F).tgz -C /opt/syba-scheduler pb_data/
```

Keep these snapshots somewhere off the firewall PC. To restore: stop the
container, replace `pb_data/`, restart.

PocketBase also has a built-in backups feature in the admin UI (Settings →
Backups) that produces downloadable archives.

## Architecture notes

- **One schedule record.** The `schedules` collection holds a single record
  with the entire schedule (teams, gyms, practices, blackouts) as a JSON
  blob plus a `version` counter. Simple, atomic, easy to back up.
- **API rules.** `listRule` and `viewRule` are empty strings, meaning
  publicly readable. `createRule` and `updateRule` require authentication.
  `deleteRule` is `null`, meaning admin-only.
- **Auto-save.** Every state mutation in the editor triggers a debounced
  PATCH to the schedule record (~600 ms). The version counter increments on
  each save.
- **Realtime sync.** Editors subscribe to the schedule record via
  PocketBase's realtime API. When another editor saves, your view updates
  automatically.
- **Concurrency model.** With 1–3 rarely-overlapping editors, last-write-wins
  is fine. If you genuinely have two people editing simultaneously and one
  is dirty when the other saves, a yellow banner warns that the next save
  will clobber the remote changes.

## Local development / testing

```bash
docker compose up
# http://localhost:8090
```

Or run PocketBase directly without Docker:

```bash
# Download the binary for your OS from https://github.com/pocketbase/pocketbase/releases
./pocketbase serve --publicDir=./pb_public --migrationsDir=./pb_migrations
```

The HTML talks to `window.location.origin`, so as long as you serve it from
the PocketBase root, it just works.

## Browser support

Tested in current Chrome, Edge, Firefox, and Safari. Desktop only —
HTML5 drag-and-drop on touch devices is unreliable.

## Calendar subscriptions for parents

The **📅 Export team calendars** button is available to everyone (no login
required) and produces one `.ics` file per team. To make these auto-updating
subscriptions, host the `.ics` files at a public URL and share
`webcal://yoursite.com/<team>.ics` with parents. Step-by-step instructions
are in the in-app help under that button.
