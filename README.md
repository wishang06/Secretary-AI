# Discord Chat Bot (Python)

Simple bot that lets people chat with it by mentioning the bot.

## Setup

1. Create a Discord application and bot in the Developer Portal.
2. Enable **Message Content Intent** for your bot.
3. Invite the bot to your server with the appropriate permissions.
4. Create an OpenAI API key and add it to `.env` as `OPENAI_API_KEY`.
5. If you're in a region where Discord is blocked, set `DISCORD_PROXY` in `.env`.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

## Notes

- The chatbot responds only when you mention the bot.
- Optional: set `OPENAI_MODEL` in `.env` to change the model.
- Optional: `DISCORD_PROXY=socks5h://127.0.0.1:7898` for Discord connectivity via SOCKS.
