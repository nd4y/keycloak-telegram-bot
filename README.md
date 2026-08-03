# Telegram bot for managing Keycloak groups

🇬🇧 **English** | [🇷🇺 Русский](README.ru.md)

The bot can:
- list groups and their members (`/groups`);
- list all users with pagination and a per-user card — their groups, add/remove group membership (`/users`);
- create groups (`/newgroup Name`);
- add a user to a group (search by username/email via buttons, or straight from the user card);
- remove a user from a group, delete a group;
- enable/disable a user (user card → status button);
- notify you in Telegram about new users and/or every login to Keycloak (checked every `POLL_INTERVAL_SECONDS`, default 60s) — both notifications toggle independently via the `/settings` command, with the container-startup default set by `NOTIFY_NEW_USERS` / `NOTIFY_LOGINS`.

Access is restricted to the Telegram IDs listed in `ADMIN_CHAT_IDS` — everyone else is silently ignored.

## 1. Create a service account client in Keycloak

The bot talks to Keycloak via the Admin REST API as a dedicated client (client credentials grant), not under your personal login.

1. Open the admin console: `https://<keycloak-host>/admin/master/console/#/<realm>`.
2. **Clients → Create client**:
   - Client ID: `telegram-bot` (or anything else, just put it in `.env` later);
   - Client type: `OpenID Connect`, click Next.
3. On the **Capability config** step:
   - `Client authentication` → **On** (makes the client confidential and enables the service account);
   - `Authorization` — can stay off;
   - `Authentication flow`: enable **Service accounts roles**, the others (Standard flow, Direct access) can be disabled.
4. Save the client.
5. Open the **Credentials** tab of the new client — copy the `Client secret`, it goes into `KEYCLOAK_CLIENT_SECRET`.
6. Open **Service account roles** → **Assign role**:
   - switch to `Filter by clients`;
   - find the `realm-management` client and assign these roles:
     - `manage-users` — creating/removing users from groups, enabling/disabling a user;
     - `query-users` — searching and listing users;
     - `query-groups` and `manage-realm` (or at least `view-realm`) — working with groups;
     - `view-events` — reading login events (only needed for `NOTIFY_LOGINS`).
   - If unsure which role to pick, you can temporarily grant `realm-admin` (full `realm-management` rights) and narrow it down later.

Result: you now have `Client ID` = `telegram-bot`, `Client secret` = a long string, realm = `<realm>`, url = `https://<keycloak-host>`.

### Optional: enable login logging (for `NOTIFY_LOGINS`)

Keycloak doesn't store login events by default — the Admin REST API will just return an empty list, even with the `view-events` role granted. For login notifications to have anything to work with:

1. In the admin console: **Realm settings → Events → User events settings**.
2. Turn on **Save events**.
3. Add (or make sure it's there) `LOGIN` under **Saved event types**.
4. Pay attention to **Expiration** — Keycloak will accumulate these events in its database; set a sane TTL (e.g. 1-2 weeks) so old events get cleaned up and don't bloat the database.

This changes realm-wide behavior (events get logged for every client, not just the bot), so enable it deliberately — it's not the same as just configuring the bot itself.

## 2. Create the Telegram bot

1. In Telegram, message [@BotFather](https://t.me/BotFather) → `/newbot` and follow the prompts.
2. You'll get a token like `123456789:AA...` — that's `TELEGRAM_BOT_TOKEN`.
3. Find your Telegram ID: message [@userinfobot](https://t.me/userinfobot) — it replies with your numeric ID. That goes into `ADMIN_CHAT_IDS` (comma-separate several IDs if there's more than one admin).

## 3. Configure .env

```bash
cp .env.example .env
```

Fill in every field: `TELEGRAM_BOT_TOKEN`, `ADMIN_CHAT_IDS`, `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`.

`NOTIFY_NEW_USERS` / `NOTIFY_LOGINS` — the default notification state at container startup; flip them live with the bot's `/settings` command, no restart needed. `PERSIST_SETTINGS` decides whether a `/settings` toggle survives a container restart:
- `false` (default) — after a restart the state falls back to `NOTIFY_NEW_USERS`/`NOTIFY_LOGINS`. Keep this if `data/` isn't mounted as persistent storage (e.g. Kubernetes without a PVC) — otherwise the toggle would appear to "save" but silently get lost on every pod recreation.
- `true` — a `/settings` toggle is written to `data/settings.json` and survives a restart. Only enable this if `data/` is a real persistent volume/bind mount.

## 4. Run with Docker

```bash
docker compose up -d --build
docker compose logs -f
```

Which users the bot has already seen (so it doesn't spam notifications on first launch) is tracked in `./data/seen_users.json`; the timestamp of the last processed login event lives in `./data/last_login_event.json`. On first startup the bot takes a "snapshot" of the current state and only notifies about what appears after that point. If `PERSIST_SETTINGS=true`, `/settings` toggles are also written there (`./data/settings.json`).

## 4b. Deploy via Portainer (no git repo, no external registry)

If the source only lives locally (not in git) and you want to deploy to a Docker host managed by Portainer:

1. Build the image directly on the Docker engine Portainer manages, via the Docker Build API (which Portainer proxies):
   ```bash
   tar -cf build-context.tar Dockerfile requirements.txt bot
   curl -sk -X POST \
     -H "X-API-Key: <PORTAINER_API_TOKEN>" \
     -H "Content-Type: application/x-tar" \
     --data-binary @build-context.tar \
     "https://<portainer-host>:9443/api/endpoints/<ENDPOINT_ID>/docker/build?t=keycloak-telegram-bot:latest"
   ```
   `ENDPOINT_ID` is the id of the target Docker environment, found via `GET /api/endpoints`.
2. Deploy the `docker-compose.portainer.yml` stack (it uses the already-built `image:` instead of `build:`, and secrets are passed as environment variables rather than an `.env` file — Portainer doesn't copy that to the host):
   ```bash
   curl -sk -X POST \
     -H "X-API-Key: <PORTAINER_API_TOKEN>" \
     -H "Content-Type: application/json" \
     -d @stack-payload.json \
     "https://<portainer-host>:9443/api/stacks?type=2&method=string&endpointId=<ENDPOINT_ID>"
   ```
   where `stack-payload.json` contains `{"Name": "...", "StackFileContent": "<contents of docker-compose.portainer.yml>", "Env": [{"name": "TELEGRAM_BOT_TOKEN", "value": "..."}, ...]}`.

When the code changes: rebuild the image with step 1 (overwrites the `latest` tag), then do an Update/Redeploy of the stack in Portainer so it picks up the new image.

## 5. Run without Docker (locally)

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env  # and fill it in
python -m bot.main
```

## Project structure

```
bot/
  config.py           — reads settings from .env
  keycloak_client.py   — async wrapper around the Keycloak Admin REST API
  storage.py           — file-backed stores for "already seen" user IDs and the last login event
  settings.py           — notification toggles (env default + optional persistence)
  callback_cache.py    — short tokens for Telegram inline buttons
  middleware.py        — restricts access to ADMIN_CHAT_IDS
  handlers.py          — commands and inline menus (/groups, /users, /settings, /newgroup, ...)
  notifier.py          — background polling of Keycloak and notifications about new users/logins
  main.py              — entry point
```

## Known limitations (MVP)

- Only top-level groups are supported (no nested subgroups).
- Notifications about new users and logins are polling-based, not instant on event; delay up to `POLL_INTERVAL_SECONDS`. Instant notifications would need a custom Keycloak Event Listener SPI on the server itself — a separate task if it's ever needed.
- Login polling fetches the last 200 events per cycle; if more than 200 logins happen between polls, some notifications could be skipped (unlikely for a personal/small realm).
