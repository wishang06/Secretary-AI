"""
Discord Bot for Secretary AI

Features:
- Chat with AI by mentioning the bot
- Transcript processing commands for meeting integration
- Status updates during processing
"""

import asyncio
import os
import ssl
import sys
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from aiohttp_socks import ProxyConnector
from openai import OpenAI

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

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

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
SYSTEM_PROMPT = (
    "You are a friendly, concise Discord chatbot assistant for a business organization. "
    "You help with meeting management, task tracking, and general information queries. "
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

# Meeting type choices for slash commands
MEETING_TYPES = [
    app_commands.Choice(name="Executive Committee", value="executive"),
    app_commands.Choice(name="Projects Subcommittee", value="projects_subcommittee"),
    app_commands.Choice(name="Events Subcommittee", value="events_subcommittee"),
    app_commands.Choice(name="Sponsorships Subcommittee", value="sponsorships_subcommittee"),
    app_commands.Choice(name="Marketing Subcommittee", value="marketing_subcommittee"),
    app_commands.Choice(name="Content Creation Subcommittee", value="content-creation_subcommittee"),
    app_commands.Choice(name="HR Subcommittee", value="hr_subcommittee"),
    app_commands.Choice(name="Full Committee", value="full"),
    app_commands.Choice(name="Unscheduled / Ad-hoc", value="unscheduled"),
]


def create_bot(
    connector: ProxyConnector | None = None,
    proxy: str | None = None,
) -> commands.Bot:
    """Create and configure the Discord bot."""

    bot = commands.Bot(
        command_prefix="!",
        intents=intents,
        connector=connector,
        proxy=proxy,
    )

    # Transcript integrator instance (initialized lazily)
    bot.transcript_integrator = None
    # In-memory short-term conversation history:
    # key: (channel_id, user_id) -> list[tuple[role, content]]
    # role is "user" or "assistant"
    bot.conversation_history: dict[tuple[int, int], list[tuple[str, str]]] = {}

    def _build_conversation_input(
        history: list[tuple[str, str]],
        user_message: str,
        max_chars: int = 3000,
        max_turns: int = 6,
    ) -> str:
        """
        Build a compact conversation transcript for the model.

        We keep only the last `max_turns` (user+assistant pairs) and trim
        the overall character length from the start if it gets too long.
        """
        if not history:
            return user_message

        # Keep only the last N turns
        trimmed_history = history[-(max_turns * 2) :]

        lines: list[str] = []
        for role, content in trimmed_history:
            prefix = "User:" if role == "user" else "Assistant:"
            lines.append(f"{prefix} {content}")

        history_text = "\n".join(lines)
        if len(history_text) > max_chars:
            history_text = history_text[-max_chars:]

        return (
            "Here is the previous conversation between you and the user:\n"
            f"{history_text}\n\n"
            f"User: {user_message}\nAssistant:"
        )

    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user} (id: {bot.user.id})")
        
        # Sync slash commands
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} slash commands")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        """Handle regular messages - AI chat when mentioned."""
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
            await bot.process_commands(message)
            return

        text = content
        for token in mention_tokens:
            text = text.replace(token, "")
        text = text.strip()

        if not text:
            text = "Hello!"
        # -------- Short-term memory handling --------
        # Use (channel_id, user_id) as the conversation key so each user has
        # separate context per channel/DM.
        key = (message.channel.id, message.author.id)
        history = bot.conversation_history.get(key, [])

        prompt_input = _build_conversation_input(history, text)

        request_kwargs = {
            "model": OPENAI_MODEL,
            "instructions": SYSTEM_PROMPT,
            "input": prompt_input,
            "max_output_tokens": 500,
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

        # Update conversation history:
        # append user message and assistant reply, then trim to last N turns.
        history.append(("user", text))
        history.append(("assistant", reply))
        # Keep only the last 10 messages (5 full turns) in raw store;
        # _build_conversation_input will trim further if needed.
        history = history[-10:]
        bot.conversation_history[key] = history

        await message.channel.send(reply)
        await bot.process_commands(message)

    # ========== TRANSCRIPT COMMANDS ==========

    async def get_integrator():
        """Get or create the transcript integrator instance."""
        if bot.transcript_integrator is None:
            from transcript_integrator.integrator import TranscriptIntegrator
            bot.transcript_integrator = TranscriptIntegrator()
            await bot.transcript_integrator.setup()
        return bot.transcript_integrator

    @bot.tree.command(name="process_transcript", description="Process a transcript file from the landing folder")
    @app_commands.describe(
        filename="Name of the transcript file in the landing folder",
        meeting_name="A descriptive name for the meeting",
        meeting_type="Type of meeting",
    )
    @app_commands.choices(meeting_type=MEETING_TYPES)
    async def process_transcript(
        interaction: discord.Interaction,
        filename: str,
        meeting_name: str,
        meeting_type: app_commands.Choice[str],
    ):
        """Process a transcript file and extract meeting information."""
        await interaction.response.defer(thinking=True)
        
        # Find the landing directory
        project_root = Path(__file__).parent.parent
        landing_dir = project_root / "landing"
        
        # Try to find the file
        file_path = None
        
        # Check root of landing
        if (landing_dir / filename).exists():
            file_path = landing_dir / filename
        else:
            # Check subfolders
            for subfolder in landing_dir.iterdir():
                if subfolder.is_dir():
                    potential_path = subfolder / filename
                    if potential_path.exists():
                        file_path = potential_path
                        break
        
        if file_path is None:
            await interaction.followup.send(
                f"File not found: `{filename}`\n"
                f"Make sure the file is in the `landing/` folder or its subfolders."
            )
            return
        
        try:
            integrator = await get_integrator()
            
            # Create status embed
            status_embed = discord.Embed(
                title="Processing Transcript",
                description=f"Analyzing `{filename}`...",
                color=discord.Color.blue()
            )
            status_embed.add_field(name="Meeting Name", value=meeting_name, inline=True)
            status_embed.add_field(name="Meeting Type", value=meeting_type.name, inline=True)
            status_embed.add_field(name="Status", value="Extracting information...", inline=False)
            
            await interaction.followup.send(embed=status_embed)
            
            # Process the transcript
            result = await integrator.process_transcript(
                transcript_path=str(file_path),
                meeting_name=meeting_name,
                meeting_type=meeting_type.value,
            )
            
            # Create result embed
            result_embed = discord.Embed(
                title="Transcript Processing Complete",
                description=f"Successfully processed `{filename}`",
                color=discord.Color.green()
            )
            result_embed.add_field(name="Meeting ID", value=str(result['meeting_id']), inline=True)
            result_embed.add_field(name="Meeting Type", value=meeting_type.name, inline=True)
            
            # Members
            members_text = ", ".join(result.get('member_names', [])) or "None identified"
            result_embed.add_field(
                name=f"Members ({result.get('members_identified', 0)})", 
                value=members_text[:1024], 
                inline=False
            )
            
            # Projects
            projects_text = ", ".join(result.get('project_names', [])) or "None linked"
            result_embed.add_field(
                name=f"Projects ({result.get('projects_linked', 0)})", 
                value=projects_text[:1024], 
                inline=False
            )
            
            # Topics
            topics_text = ", ".join(result.get('topic_names', [])) or "None identified"
            new_topics = result.get('new_topics_created', 0)
            result_embed.add_field(
                name=f"Topics ({result.get('topics_linked', 0)}, {new_topics} new)", 
                value=topics_text[:1024], 
                inline=False
            )
            
            # Tasks
            tasks_text = "\n".join([f"- {t}" for t in result.get('task_names', [])]) or "None created"
            result_embed.add_field(
                name=f"Tasks ({result.get('tasks_created', 0)})", 
                value=tasks_text[:1024], 
                inline=False
            )
            
            result_embed.set_footer(text=f"Summary: {result.get('summary_length', 0)} characters")
            
            await interaction.channel.send(embed=result_embed)
            
        except Exception as e:
            error_embed = discord.Embed(
                title="Processing Error",
                description=f"Failed to process transcript: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed)

    @bot.tree.command(name="list_transcripts", description="List transcript files in the landing folder")
    async def list_transcripts(interaction: discord.Interaction):
        """List available transcript files in the landing folder."""
        await interaction.response.defer()
        
        project_root = Path(__file__).parent.parent
        landing_dir = project_root / "landing"
        
        if not landing_dir.exists():
            await interaction.followup.send("Landing folder not found.")
            return
        
        # Collect all transcript files
        files_by_folder = {}
        
        # Root folder files
        root_files = [f.name for f in landing_dir.iterdir() 
                     if f.is_file() and f.suffix.lower() in ['.txt', '.md']]
        if root_files:
            files_by_folder['(root)'] = root_files
        
        # Subfolder files
        for subfolder in sorted(landing_dir.iterdir()):
            if subfolder.is_dir() and not subfolder.name.startswith('.'):
                folder_files = [f.name for f in subfolder.iterdir() 
                               if f.is_file() and f.suffix.lower() in ['.txt', '.md']]
                if folder_files:
                    files_by_folder[subfolder.name] = folder_files
        
        if not files_by_folder:
            await interaction.followup.send(
                "No transcript files found in the landing folder.\n"
                "Drop `.txt` or `.md` files into the `landing/` folder to process them."
            )
            return
        
        # Create embed
        embed = discord.Embed(
            title="Available Transcripts",
            description="Transcript files in the landing folder",
            color=discord.Color.blue()
        )
        
        for folder, files in files_by_folder.items():
            file_list = "\n".join([f"- `{f}`" for f in files[:10]])
            if len(files) > 10:
                file_list += f"\n... and {len(files) - 10} more"
            embed.add_field(name=f"{folder}/", value=file_list, inline=False)
        
        embed.set_footer(text="Use /process_transcript to analyze a file")
        
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="meeting_stats", description="Get statistics about processed meetings")
    async def meeting_stats(interaction: discord.Interaction):
        """Get statistics about meetings in the database."""
        await interaction.response.defer()
        
        try:
            integrator = await get_integrator()
            
            # Query database for stats
            from sqlalchemy import select, func
            from transcript_integrator.models import Meeting, Task, Topic
            
            async with integrator.async_session() as session:
                # Count meetings
                meetings_count = await session.scalar(
                    select(func.count()).select_from(Meeting)
                )
                
                # Count tasks
                tasks_count = await session.scalar(
                    select(func.count()).select_from(Task)
                )
                
                # Count topics
                topics_count = await session.scalar(
                    select(func.count()).select_from(Topic)
                )
                
                # Recent meetings
                recent_meetings = await session.execute(
                    select(Meeting.meeting_name, Meeting.meeting_type, Meeting.ingestion_timestamp)
                    .order_by(Meeting.ingestion_timestamp.desc())
                    .limit(5)
                )
                recent = recent_meetings.fetchall()
            
            # Create embed
            embed = discord.Embed(
                title="Meeting Statistics",
                description="Overview of processed meeting data",
                color=discord.Color.green()
            )
            
            embed.add_field(name="Total Meetings", value=str(meetings_count or 0), inline=True)
            embed.add_field(name="Total Tasks", value=str(tasks_count or 0), inline=True)
            embed.add_field(name="Total Topics", value=str(topics_count or 0), inline=True)
            
            embed.add_field(name="Members Loaded", value=str(len(integrator.committee_members)), inline=True)
            embed.add_field(name="Projects Loaded", value=str(len(integrator.projects)), inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            
            if recent:
                recent_text = "\n".join([
                    f"- **{name}** ({mtype})" 
                    for name, mtype, _ in recent
                ])
                embed.add_field(name="Recent Meetings", value=recent_text[:1024], inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"Error getting stats: {str(e)}")

    @bot.tree.command(name="start_watcher", description="Information about the file watcher")
    async def start_watcher(interaction: discord.Interaction):
        """Show information about the file watcher."""
        project_root = Path(__file__).parent.parent
        landing_dir = project_root / "landing"
        
        embed = discord.Embed(
            title="File Watcher",
            description="The file watcher monitors the landing folder for new transcripts.",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Landing Folder",
            value=f"`{landing_dir}`",
            inline=False
        )
        
        embed.add_field(
            name="To Start the Watcher",
            value=(
                "Run this command in your terminal:\n"
                "```bash\n"
                "python -m transcript_integrator.file_watcher\n"
                "```"
            ),
            inline=False
        )
        
        embed.add_field(
            name="Or Process Files Manually",
            value=(
                "Use `/list_transcripts` to see available files\n"
                "Use `/process_transcript` to process a specific file"
            ),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)

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
