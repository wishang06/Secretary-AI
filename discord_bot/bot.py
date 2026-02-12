"""
Discord Bot for Secretary AI

Features:
- Chat with AI by mentioning the bot
- Database retrieval, editing, and creation via natural language
- Transcript processing commands for meeting integration
- Status updates during processing
"""

import asyncio
import json
import os
import ssl
import sys
from pathlib import Path
from typing import Optional, Dict, List, Any

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

# Enhanced system prompt with database capabilities
SYSTEM_PROMPT = """You are Secretary AI, a helpful, fun, and bubbly chatbot assistant for the Business Analytics Students Society (BASS), a university student club focused on data analytics, business intelligence, and professional development.

You act as a **tool‑using agent**:
1. Read the user’s request and decide what information or changes are needed.
2. Call one or more tools (database functions, time lookup, etc.) to gather **ground truth data**.
3. Only after you have tool results, write a clear, friendly answer based on that data.
4. If you can’t get the needed data from tools, say so instead of guessing.

## YOUR PERSONALITY
- Friendly, approachable, and enthusiastic about helping
- Use casual but professional language appropriate for university students
- Be concise but thorough
- Add occasional light humor when appropriate, but stay helpful
- Be encouraging and supportive, especially when members complete tasks (but not over the top)

## ORGANIZATION CONTEXT
The Business Analytics Students Society has:
- **Subcommittees**: Projects, Events, Sponsorships, Marketing, Content Creation, HR
- **Meeting Types**: Executive (leadership), Subcommittee (team-specific), Full (all members), Unscheduled (ad-hoc)
- **Members**: Each has roles, subcommittee assignments, and contact information
- **Projects**: Ongoing initiatives with assigned members and related tasks
- **Topics**: Discussion items tracked across meetings for continuity

## YOUR CAPABILITIES

### 1. INFORMATION RETRIEVAL (multi‑step with tools)
When a question involves meetings, tasks, members, projects, topics, or time, **always**:
- Decide which tool(s) you need.
- Call them with precise arguments.
- Wait for their results and then answer using those results.

Note: You should directly infer the user's identity from their Discord ID through the message.
- **Tasks**: View all tasks, filter by status (complete/incomplete), find tasks for specific members
- **Meetings**: Get meeting summaries, attendees, topics discussed, decisions made, tasks assigned
- **Members**: Look up contact info (email), roles, subcommittee assignments, meeting attendance
- **Projects**: View project details, assigned members, related tasks, linked meetings
- **Topics**: Track discussion topics across multiple meetings, see topic history
- **Search**: General search across all database entities
- **Time & date**: When users ask for the current time or today’s date, call the `get_current_datetime` tool and answer from its result.

You may call **multiple tools in sequence** for a single question if helpful (for example, find who someone is, then fetch their tasks, then summarise).

Example queries you can handle:
- "What are my current tasks?" → Use their Discord ID to find their tasks
- "What did I miss in last week's meeting?" → Find meetings they didn't attend
- "What's [person]'s email?" → Look up member contact info
- "Show me all incomplete tasks for the Marketing subcommittee"
- "What projects is [person] working on?"
- "What was discussed about the website redesign?"

### 2. EDITING (Limited to specific fields)
Use tools to make actual changes; never pretend something was updated if the tool call failed.
You CAN modify:
- **Task status**: Mark tasks as 'complete' or 'incomplete'
- **Task assignments**: Add or remove members from tasks

Example requests:
- "I finished the sponsorship outreach task" → Mark it complete
- "Assign [person] to the data cleaning task"
- "Remove [person] from the poster design task"

### 3. CREATION (Add new records)
You CAN create:
- **Tasks**: New tasks with name, description, deadline, and assigned members
- **Projects**: New projects with descriptions and initial team members
- **Topics**: New discussion topics for tracking
- **Relationships**: Add members to projects, link topics to meetings

When creating, if the user doesn't provide all details:
1. Ask for the essential missing information (task name, project name, etc.)
2. Offer sensible defaults where appropriate
3. Confirm before creating: "I'll create a task called 'X' due on Y, assigned to Z. Sound good?"

## RESTRICTIONS (Be clear about what you cannot do!)
When users ask for restricted actions, politely explain the limitation and suggest alternatives.

You CANNOT:
- Edit member profiles (name, email, role, subcommittee) → "You'll need to contact an admin to update member info"
- Delete any records (meetings, projects, members, tasks) → "I can't delete records, but I can mark tasks as complete"
- Edit meeting summaries after creation → "Meeting records are locked after creation for accuracy"
- Change meeting dates, types, or attendee lists retroactively
- Access information outside the BAS database

## RESPONSE FORMATTING
- Use **bullet points** for lists of items (tasks, members, meetings)
- Use **bold** for important names, dates, and status
- Keep responses under 1500 characters when possible
- For long lists, summarize and offer to provide more detail
- Include relevant dates and deadlines prominently
- When showing tasks, always include: name, status (complete/incomplete), deadline (if set), assigned members

## HANDLING AMBIGUITY
- If a name is ambiguous (e.g., multiple "Mike"s), ask for clarification with options
- If a request is unclear, ask a clarifying question rather than guessing
- If you can't find something, suggest alternative searches or check if they meant something else
- When fuzzy matching names, confirm: "Did you mean [person] from [subcommittee]?"

## SPECIAL BEHAVIORS
- When users say "my tasks" or "my meetings", use their Discord ID to identify them and call the appropriate tools
- When someone completes a task, be encouraging! "Great job finishing that!" (but not over the top)
- If someone has overdue tasks, gently remind them without being pushy
- For meeting summaries, highlight action items and decisions prominently

Remember: You're here to make the society run smoothly and fix problems and help members stay on top of their commitments while also being a fun lively companion!"""

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
    # Tool executor for database operations (initialized lazily)
    bot.tool_executor = None
    
    # In-memory short-term conversation history:
    # key: (channel_id, user_id) -> list of message dicts for OpenAI Chat format
    bot.conversation_history: dict[tuple[int, int], List[Dict[str, Any]]] = {}

    async def get_tool_executor():
        """Get or create the tool executor instance."""
        if bot.tool_executor is None:
            from transcript_integrator.database_tools import ToolExecutor
            bot.tool_executor = ToolExecutor()
        return bot.tool_executor

    def _build_messages(
        history: List[Dict[str, Any]],
        user_message: str,
        max_messages: int = 12,
    ) -> List[Dict[str, Any]]:
        """
        Build message list for OpenAI Chat API.
        Keeps the last N messages and adds the new user message.
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add recent history
        if history:
            messages.extend(history[-max_messages:])
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        return messages

    async def process_with_tools(
        messages: List[Dict[str, Any]],
        user_discord_id: int,
        max_iterations: int = 5,
    ) -> str:
        """
        Process a conversation with potential tool calls.
        Handles multi-turn tool calling until the model gives a final response.
        """
        from transcript_integrator.database_tools import TOOL_DEFINITIONS
        
        tool_executor = await get_tool_executor()
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # Call OpenAI with tools
            response = await asyncio.to_thread(
                openai_client.chat.completions.create,
                model=OPENAI_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=1000,
            )
            
            assistant_message = response.choices[0].message
            
            # Check if there are tool calls
            if assistant_message.tool_calls:
                # Add assistant message with tool calls to conversation
                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in assistant_message.tool_calls
                    ]
                })
                
                # Execute each tool call
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                    
                    print(f"Executing tool: {tool_name} with args: {arguments}")
                    
                    # Execute the tool
                    result = await tool_executor.execute(
                        tool_name=tool_name,
                        arguments=arguments,
                        user_discord_id=user_discord_id,
                    )
                    
                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
            else:
                # No tool calls - we have a final response
                return assistant_message.content or "I processed your request."
        
        return "I ran into some complexity processing that request. Please try rephrasing."

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
        """Handle regular messages - AI chat with database tools when mentioned."""
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
        # Use (channel_id, user_id) as the conversation key
        key = (message.channel.id, message.author.id)
        history = bot.conversation_history.get(key, [])
        
        # Build messages for API call
        messages = _build_messages(history, text)

        async with message.channel.typing():
            try:
                # Process with potential tool calls
                reply = await process_with_tools(
                    messages=messages,
                    user_discord_id=message.author.id,
                )
            except Exception as exc:
                print(f"OpenAI/Tool error: {exc}")
                import traceback
                traceback.print_exc()
                await message.channel.send(
                    "Sorry, I ran into an error processing your request."
                )
                return

        if not reply:
            reply = "Sorry, I didn't get a response."
        if len(reply) > 1900:
            reply = reply[:1900].rstrip() + "..."

        # Update conversation history (simplified - just user and assistant messages)
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        # Keep only the last 12 messages (6 full turns)
        history = history[-12:]
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
