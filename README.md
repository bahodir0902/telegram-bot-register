# Telegram Registration Bot

A small Telegram-native bot that verifies a user's own phone contact, checks membership in
one configured channel, and delivers all active media. Administrators add and manage media
entirely through the bot.

## Architecture

The application is one asynchronous Python process using:

- aiogram 3 long polling for Telegram updates;
- SQLAlchemy 2 async ORM with aiosqlite;
- one SQLite database configured with WAL, foreign keys, and a busy timeout;
- pydantic-settings for validated environment configuration;
- aiogram's in-memory FSM only while an administrator is uploading media.

Durable onboarding and media state lives in SQLite. Telegram-originated media is stored by its
reusable Telegram `file_id`; the bot does not download and re-upload it. `MEDIA_ROOT` is created
for future local-file use but is not required by the current delivery flow.

## Requirements

- Python 3.14+ for local development
- A Telegram bot token from [BotFather](https://t.me/BotFather)
- One Telegram channel
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
database is missing, corrupt, or does not contain the expected `users` and `media` tables.

The dispatcher removes any existing webhook and starts long polling. SIGINT and SIGTERM are
handled by aiogram's polling runner, after which the Telegram session and database engine close.

## Configuration

All deployment values come from environment variables. A local `.env` file is supported and is
ignored by Git.

| Variable | Required | Description |
| --- | --- | --- |
| `BOT_TOKEN` | Yes | BotFather token. It is treated as a secret and is not logged. |
| `CHANNEL_ID` | Yes | Numeric channel ID such as `-1001234567890`, or public `@username`. |
| `CHANNEL_URL` | Yes | Telegram HTTPS URL used by the Subscribe button, including private invite links. |
| `ADMIN_IDS` | Yes | Comma-separated positive Telegram user IDs, for example `123,456`. |
| `DATABASE_PATH` | No | SQLite path; defaults to `./data/bot.sqlite3`. |
| `MEDIA_ROOT` | No | Reserved local media directory; defaults to `./media`. |

Startup fails with field-specific errors if required values are missing or malformed. Never put a
real token in `.env.example` or source code.

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
| `CHANNEL_ID` | Numeric channel ID or `@username`. |
| `CHANNEL_URL` | Valid Telegram HTTPS link. |
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

The workflow files are ready for a future GitHub repository, but this implementation does not
initialize Git, configure a remote, or push anything externally.

## Telegram and channel setup

1. Create the bot with BotFather and place its token in `BOT_TOKEN`.
2. Add the bot to the target channel as an administrator.
3. Put the channel's API identifier in `CHANNEL_ID` and its public or invite link in
   `CHANNEL_URL`.
4. Put each administrator's numeric Telegram user ID in `ADMIN_IDS`.
5. Start the process and talk to the bot in a private chat.

Telegram only guarantees `getChatMember` results for other users when the bot is an administrator
in the chat. Therefore, channel administrator access is an operational requirement, not an
optional enhancement. The bot does not need permission to publish channel posts, but it must
remain an administrator with enough access for reliable membership queries.

For a private channel, use its internal `-100...` ID for `CHANNEL_ID` and a valid `https://t.me/+...`
invite link for `CHANNEL_URL`.

## User flow

1. `/start` upserts the user and sends a separate welcome message.
2. An unverified user receives a native `request_contact` reply keyboard.
3. The bot accepts the contact only when `contact.user_id` matches the sender, stores the
   normalized phone number, and removes the reply keyboard.
4. A separate message asks the user to join the configured channel.
5. `Check subscription` is answered immediately and performs a live Telegram membership lookup.
6. A failed check updates the existing prompt and keeps its buttons. A successful check edits the
   same prompt, removes the buttons, and sends active media in `(sort_order, id)` order.

The current prompt message ID is persisted and atomically claimed, so double-clicking the same
successful check does not send the media twice. Repeating `/start` never creates a duplicate user
and creates a fresh subscription prompt so membership can be checked again.

## Administrator flow

Send `/admin` in a private chat from an ID listed in `ADMIN_IDS`.

- **Add media** waits for one video, photo, or document. The reusable `file_id`, optional
  `file_unique_id`, filename, type, and caption are stored. New items are active and receive the
  next sort order in increments of 10.
- **Manage media** shows five records per page. An administrator can inspect, enable, disable, or
  delete a record. Deletion requires confirmation and does not attempt to remove Telegram's
  underlying object.
- `/cancel` exits an active upload prompt.

Every administrator command and callback checks the current sender ID against `ADMIN_IDS`.
Callback data never grants authorization by itself.

## Database

`users` stores the Telegram identity, optional profile data, verified phone and subscription
timestamps, and the current subscription prompt ID. `media` stores Telegram file references,
media type, optional filename/caption, active state, ordering, and timestamps.

The schema is initialized programmatically on startup. V1 has no migration framework, so future
schema changes must add a migration strategy before deployment to an existing database.

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

- One process, one SQLite database, and one required channel.
- Long polling only; no webhook or HTTP server.
- No delivery history or exactly-once guarantee across manual creation of multiple prompts.
- No media reordering UI; order is assigned when media is added.
- No local upload storage, scheduled campaigns, audience targeting, or web dashboard.
- In-memory admin upload state is intentionally lost on restart; durable media is not.
