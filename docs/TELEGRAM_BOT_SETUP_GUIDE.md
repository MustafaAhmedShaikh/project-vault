# Telegram Alerts Setup

Telegram alerts are optional. When set up, ProjectVault sends you a message when a backup succeeds and when it fails. Failure messages start with "FAILED". Setup takes a few minutes and is free.

## Step 1: Create a bot

1. In Telegram, open a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot`.
3. Enter a display name (for example `My Project Backups`).
4. Enter a username that ends in `bot` (for example `my_project_backup_bot`).
5. BotFather replies with a token. It looks like this (this one is fake):

   ```text
   123456789:ABC-DEF_replace-with-your-own-token
   ```

Treat the token like a password. Anyone who has it can control your bot.

## Step 2: Find your chat ID

1. Open your new bot in Telegram and press **Start** (or send any message). The bot can only message you after you do this.
2. In a browser, open this address, replacing the placeholder with your token:

   ```text
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```

3. Find `"chat":{"id":123456789` in the reply. That number is your chat ID.

Do not paste this address into chat apps or issues; it contains your token.

## Step 3: Add both values to `.env`

```ini
TELEGRAM_BOT_TOKEN="123456789:ABC-DEF_replace-with-your-own-token"
TELEGRAM_CHAT_ID="123456789"
```

## Step 4: Test it

```bash
python vault_backup.py --test-alert
```

You should get a test message within a few seconds. If you also set `NTFY_TOPIC`, the test goes there too.

## Notes

- ProjectVault talks to `api.telegram.org` over HTTPS with normal certificate checks.
- If you are behind a proxy, set the standard `HTTPS_PROXY` environment variable. It is used automatically.
- If Telegram is blocked on your network, use a VPN or proxy, or use ntfy instead (below).
- Tokens are not written to the logs.
- Never commit `.env`. If your token leaks, send `/revoke` to BotFather and put the new token in `.env`.

## Alternative: ntfy

[ntfy](https://ntfy.sh) needs no account. Install the ntfy app on your phone, subscribe to a long, random topic name, then set:

```ini
NTFY_TOPIC="my-project-backups-x8k2q9"
# NTFY_SERVER="https://ntfy.sh"   # change only if you run your own server
```

Anyone who knows the topic name can read the messages on the public server, so choose one that is hard to guess.

## Not working?

See [Troubleshooting](TROUBLESHOOTING.md).
