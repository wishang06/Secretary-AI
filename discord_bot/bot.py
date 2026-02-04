import asyncio
import os
import ssl
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv
from aiohttp_socks import ProxyConnector
from openai import OpenAI

load_dotenv()

try:
    import certifi
except ImportError:
    certifi = None

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("Missing DISCORD_TOKEN. Copy .env.example to .env and set the token.")
    sys.exit(1)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("Missing OPENAI_API_KEY. Copy .env.example to .env and set the key.")
    sys.exit(1)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")
SYSTEM_PROMPT = (
    "You are a friendly, concise Discord chatbot. "
    "Keep responses to 1-3 sentences unless asked otherwise."
)

DISCORD_PROXY = os.getenv("DISCORD_PROXY")
DISCORD_PROXY_NORMALIZED = (
    DISCORD_PROXY.replace("socks5h://", "socks5://", 1)
    if DISCORD_PROXY
    else None
)

intents = discord.Intents.default()
intents.message_content = True

openai_client = OpenAI()


def create_bot(
    connector: ProxyConnector | None = None,
    proxy: str | None = None,
) -> commands.Bot:
    bot = commands.Bot(
        command_prefix="!",
        intents=intents,
        connector=connector,
        proxy=proxy,
    )

    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user} (id: {bot.user.id})")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return

        if bot.user is None:
            return

        content = message.content.strip()
        if not content:
            return

        mention_tokens = [f"<@{bot.user.id}>", f"<@!{bot.user.id}>"]
        is_mentioned = (bot.user in message.mentions) or any(
            token in content for token in mention_tokens
        )
        if not is_mentioned:
            return

        text = content
        for token in mention_tokens:
            text = text.replace(token, "")
        text = text.strip()

        if not text:
            text = "Hello!"

        request_kwargs = {
            "model": OPENAI_MODEL,
            "instructions": SYSTEM_PROMPT,
            "input": text,
            "max_output_tokens": 200,
        }

        async with message.channel.typing():
            try:
                response = await asyncio.to_thread(
                    openai_client.responses.create,
                    **request_kwargs,
                )
            except Exception as exc:
                print(f"OpenAI error: {exc}")
                await message.channel.send(
                    "Sorry, I ran into an error talking to the AI."
                )
                return

        reply = (response.output_text or "").strip()
        if not reply:
            reply = "Sorry, I didn't get a response."
        if len(reply) > 1900:
            reply = reply[:1900].rstrip() + "..."

        await message.channel.send(reply)

    return bot


if __name__ == "__main__":
    async def main() -> None:
        connector: ProxyConnector | None = None
        proxy: str | None = None

        ssl_context = None
        if certifi is not None:
            os.environ.setdefault("SSL_CERT_FILE", certifi.where())
            ssl_context = ssl.create_default_context(cafile=certifi.where())

        if DISCORD_PROXY_NORMALIZED:
            if DISCORD_PROXY_NORMALIZED.startswith("socks5://"):
                connector = ProxyConnector.from_url(
                    DISCORD_PROXY_NORMALIZED,
                    ssl=ssl_context,
                )
            else:
                proxy = DISCORD_PROXY_NORMALIZED

        bot = create_bot(connector=connector, proxy=proxy)
        async with bot:
            await bot.start(TOKEN)

    asyncio.run(main())
