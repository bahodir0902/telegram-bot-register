# Telegram Registration Bot

A small multilingual Telegram-native bot that verifies a user's own phone contact, checks
membership in every administrator-managed channel, and presents administrator-defined options.
Each option delivers its own localized text/media content. Administrators manage options,
channels, and broadcasts entirely through the bot.

## Architecture

The application is one asynchronous Python process using:

- aiogram 3 long polling for Telegram updates;
- SQLAlchemy 2 async ORM with aiosqlite;
- one SQLite database configured with WAL, foreign keys, and a busy timeout;
- pydantic-settings for validated environment configuration;
- aiogram's in-memory FSM while an administrator is composing content or editing channels.

Durable onboarding, channel, option/content, and confirmed-broadcast state lives in SQLite. Each
option has Uzbek, Russian, and English button names and one or more ordered content items with
localized text/captions. A background worker sends one broadcast at a time and resumes pending
recipients after restart. Telegram media is stored by reusable `file_id`; the bot does not
download and re-upload it. `MEDIA_ROOT` is created for future local-file use but is not required
by the current delivery flow.

## Requirements

- Python 3.14+ for local development
- A Telegram bot token from [BotFather](https://t.me/BotFather)
- At least one Telegram channel
- The numeric Telegram user IDs of all administrators

## Local setup

With [uv](https://docs.astral.sh/uv/):

```bash
uv sync --dev --python 3.14
cp .env.example .env
```

Edit `.env`, then validate configuration and initialize the database without contacting
Telegram:

```bash
.venv/bin/python -m app --check
```

Run the bot:

```bash
.venv/bin/python -m app
```

Check an already initialized database without changing it or contacting Telegram:

```bash
.venv/bin/python -m app --healthcheck
```

Unlike `--check`, the health check never creates the database or schema. It fails when the
database is missing, corrupt, or does not contain the expected current schema.

The dispatcher removes any existing webhook and starts long polling. SIGINT and SIGTERM are
handled by aiogram's polling runner, after which the Telegram session and database engine close.

## Configuration

All deployment values come from environment variables. A local `.env` file is supported and is
ignored by Git.

| Variable | Required | Description |
| --- | --- | --- |
| `BOT_TOKEN` | Yes | BotFather token. It is treated as a secret and is not logged. |
| `CHANNEL_ID` | Yes | Bootstrap channel ID such as `-1001234567890`, or public `@username`. |
| `CHANNEL_URL` | Yes | Bootstrap channel HTTPS join URL, including private invite links. |
| `ADMIN_IDS` | Yes | Comma-separated positive Telegram user IDs, for example `123,456`. |
| `DATABASE_PATH` | No | SQLite path; defaults to `./data/bot.sqlite3`. |
| `MEDIA_ROOT` | No | Reserved local media directory; defaults to `./media`. |

Startup fails with field-specific errors if required values are missing or malformed. On a normal
start, the environment channel is validated through Telegram and inserted only when the channels
table is empty. Once a channel exists, administrator changes in SQLite are authoritative and later
environment changes do not overwrite them. Never put a real token in `.env.example` or source code.

In the production container, `DATABASE_PATH` is fixed to `/app/data/bot.sqlite3` and `MEDIA_ROOT`
to `/app/media`. Both directories are backed by named Docker volumes.

## Production container

The multi-stage image is built for `linux/amd64` from digest-pinned Python and uv images. uv and
the builder stage are not copied into the runtime stage. The runtime process has fixed UID/GID
`10001`, exposes no port, runs on a read-only root filesystem through Compose, and uses
`python -m app --healthcheck` as its Docker health check.

`compose.yaml` deliberately defines one bot replica and no other service. It requires `BOT_IMAGE`
to be the exact published `ghcr.io/...@sha256:...` reference and reads bot configuration from a
mode-`0600` `bot.env`. Its named volumes are:

- `telegram-registration-bot-data` for SQLite;
- `telegram-registration-bot-media` for the reserved media directory.

Do not scale the service. SQLite and Telegram long polling make this deployment intentionally
single-process.

## GitHub Actions CI/CD

[`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml) runs for pull requests to `main`,
pushes to `main`, and manual dispatches. Pull requests stop after `Verify` and `Test`. Successful
`main` runs continue through these stages:

1. `Verify` scans full Git history with Gitleaks, runs Semgrep Python/security rules with metrics
   disabled, scans source/dependencies/secrets/Docker configuration with Trivy, validates the
   deployment shell script, and renders Compose with dummy values.
2. `Test` verifies `uv.lock`, installs Python 3.14.7 and locked development dependencies, then runs
   Ruff formatting/lint checks and pytest.
3. `Build and publish` builds only `linux/amd64`, publishes lowercase GHCR tags
   `sha-<commit>` and `latest`, and blocks deployment if the published digest has a fixed
   HIGH/CRITICAL OS or Python vulnerability.
4. `Deploy production` transfers the exact image digest and configuration over host-key-verified
   SSH, authenticates Docker to GHCR with the short-lived workflow token, and waits for health.
   A failed rollout automatically restores the previous Compose file, image digest, and runtime
   environment. Named volumes are never removed by deployment or rollback.
5. `Clean old GHCR versions` runs only after a healthy deployment and retains the newest two
   container versions.

Production workflow runs are serialized and are never cancelled by a newer run. Reusable actions,
scanner containers, the Python base image, and the uv image are pinned to immutable commits or
digests.

### Repository configuration

The default and deployment branch must be `main`. Create a GitHub environment named
`production`; no required-reviewer gate is expected by this workflow. Configure these repository
secrets:

| Secret | Purpose |
| --- | --- |
| `BOT_TOKEN` | Production BotFather token. |
| `VPS_SSH_PRIVATE_KEY` | Unencrypted private key for the deploy user. |
| `VPS_HOST` | VPS DNS name or IPv4 address. |
| `VPS_USERNAME` | SSH user allowed to run Docker. |
| `VPS_KNOWN_HOSTS` | Pinned OpenSSH `known_hosts` entry for the VPS. |

Configure these repository variables:

| Variable | Purpose |
| --- | --- |
| `CHANNEL_ID` | Initial numeric channel ID or `@username`, used only to bootstrap an empty database. |
| `CHANNEL_URL` | Initial valid Telegram HTTPS join link, used with `CHANNEL_ID`. |
| `ADMIN_IDS` | Comma-separated positive Telegram user IDs. |
| `VPS_PORT` | SSH port; leave unset to use `22`. |

Obtain the host key from a trusted channel or VPS console and verify its fingerprint before
putting the complete entry in `VPS_KNOWN_HOSTS`. The workflow intentionally never disables SSH
host-key checking.

Protect `main` with the `Verify` and `Test` jobs as required checks. The workflow uses only the
built-in `GITHUB_TOKEN`; no long-lived GHCR personal access token is required.

### VPS prerequisites and first deployment

The VPS must be `linux/amd64` and have Docker Engine plus Docker Compose v2 with support for
`docker compose up --wait`. The SSH deploy user must be able to run Docker without an interactive
password prompt. The host needs outbound HTTPS access to Telegram and GHCR; no inbound bot port is
required.

The workflow creates `$HOME/apps/telegram-registration-bot` on the VPS. During each rollout it
stores `compose.yaml`, `image.env`, and mode-`0600` `bot.env` there. It also keeps `.previous`
copies for rollback. The GHCR login uses the job-scoped token and is logged out when the job ends,
which also permits the first deployment while the newly created package is still private.

After the first successful publication:

1. Change the GHCR package visibility to **Public**.
2. In the package settings, confirm this repository has **Admin** access. That permission is
   required by the package cleanup job.
3. Confirm the production environment and branch protection are configured as described above.

## Telegram and channel setup

1. Create the bot with BotFather and place its token in `BOT_TOKEN`.
2. Add the bot to the initial channel as an administrator.
3. Put that channel's API identifier in `CHANNEL_ID` and its public or invite link in
   `CHANNEL_URL`.
4. Put each administrator's numeric Telegram user ID in `ADMIN_IDS`.
5. Start the process and talk to the bot in a private chat.

The first normal startup validates and stores the environment channel. Add every later channel
through **Administration → Channels**. The bot fetches each title from Telegram and refuses a
channel unless it is a Telegram channel and the bot is its administrator.

Telegram only guarantees `getChatMember` results for other users when the bot is an administrator
in the chat. Therefore, administrator access in every managed channel is an operational
requirement. The bot does not need permission to publish posts, but it must remain an
administrator with enough access for reliable membership queries.

For a private channel, use its internal `-100...` ID for `CHANNEL_ID` and a valid `https://t.me/+...`
invite link for `CHANNEL_URL`.

## User flow

1. A first `/start` requires the user to choose Uzbek, Russian, or English. Uzbek is the safe
   fallback until a choice is stored.
2. The bot sends a localized welcome. An unverified user receives a native `request_contact`
   reply keyboard.
3. The bot accepts the contact only when `contact.user_id` matches the sender, stores the
   normalized phone number, and replaces the contact keyboard with the persistent language button.
4. A persistent `Til / Язык / Language` button and `/language` allow switching at any time.
5. A separate message asks the user to join every managed channel.
6. `Check subscription` is answered immediately and performs live Telegram membership lookups.
7. A failed or partial check updates the existing prompt and keeps its buttons. A successful check
   replaces the same prompt with up to eight active option buttons per page. It does not
   automatically send content.
8. Pressing an option performs a fresh all-channel membership check. If membership still passes,
   the bot sends that option's content in `(sort_order, id)` order using the user's selected
   language. A missing subscription restores the channel gate; a changed channel list requires a
   fresh check.

The current prompt message ID is persisted and atomically claimed, so double-clicking the same
successful check does not render duplicate menus. Repeating `/start` never creates a duplicate
user and creates a fresh subscription prompt so membership can be checked again.

## Administrator flow

Send `/admin` in a private chat from an ID listed in `ADMIN_IDS`.

- **Add option** collects the button name in Uzbek, Russian, and English, then accepts one or more
  text, photo, video, or document items. Each item has Uzbek, Russian, and English text/caption
  variants. The option is saved only after at least one complete item exists.
- **Manage options** shows five options per page. An administrator can inspect, reorder, enable,
  disable, rename in any language, or delete an option. Each option's content list is separately
  paginated and supports adding, replacing, reordering, editing all three localized texts, and
  confirmed deletion. Deleting the final item automatically disables its option; an empty option
  cannot be enabled.
- **Send broadcast** collects the same supported content and three language variants, shows a
  preview, and asks for confirmation. Confirmation snapshots all currently reachable users.
  Sending continues in the background, with refreshable progress and cancellation for recipients
  not yet sent.
- **Channels** shows five records per page. Administrators can add channels, replace their
  Telegram ID or join link, and delete records with confirmation. IDs are validated live and
  titles are fetched from Telegram. The final channel cannot be deleted.
- `/cancel` exits an active option, broadcast, or channel-editing prompt.

Every administrator command and callback checks the current sender ID against `ADMIN_IDS`.
Callback data never grants authorization by itself.

## Database

`users` stores the Telegram identity, selected language, profile/verification data, current
subscription prompt ID, and whether Telegram still considers the user reachable. `channels`
stores the Telegram identifier, fetched title, join URL, and timestamps. `content_options` stores
localized button names, active state, and ordering. `option_content_items` stores the option-owned
text or Telegram file references, three localized text/caption variants, and per-option ordering.
`broadcasts` and `broadcast_recipients` persist confirmed jobs, immutable audience snapshots,
retries, progress, and cancellation state.

The schema uses versioned SQLite migrations through `PRAGMA user_version`. This release
upgrades the original users/media schema in place. Existing global content is preserved inside one
disabled **Imported content** option so an administrator can rename, review, and explicitly enable
it. A database with an unknown future version or an incomplete schema is rejected rather than
silently repaired.

### Backup

For the simplest consistent backup, stop the bot cleanly, copy the SQLite file at
`DATABASE_PATH`, then restart the bot. If online backups become necessary, use SQLite's backup API
or the `sqlite3` CLI `.backup` command rather than copying only the main file while WAL writes are
active. Telegram media itself remains hosted by Telegram; the database file IDs are therefore an
important part of the backup.

For the Compose deployment, run the following from
`$HOME/apps/telegram-registration-bot` on the VPS:

```bash
docker compose --env-file image.env stop bot
docker compose --env-file image.env cp bot:/app/data/bot.sqlite3 ./bot.sqlite3.backup
docker compose --env-file image.env start bot
```

Keep the backup outside the named volume. Restores should likewise be performed only while the bot
is stopped and should preserve ownership for UID/GID `10001`.

## Development checks

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pytest -q
```

Tests mock Telegram network boundaries and use temporary SQLite databases.

## Current limitations

- One process, one SQLite database, and at least one required managed channel.
- Long polling only; no webhook or HTTP server.
- Telegram has no idempotency key for sends, so a process loss after Telegram accepts a broadcast
  message but before SQLite records success can duplicate that one recipient on recovery.
- No content reordering UI; order is assigned when content is added.
- No local upload storage, scheduled campaigns, audience targeting, or web dashboard.
- Unconfirmed admin drafts are in memory and are intentionally lost on restart; confirmed
  broadcasts and saved content are durable.
