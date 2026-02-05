"""
Secretary AI - Main Entry Point

This script provides a unified interface for running different components:
- Discord Bot: Chat and transcript processing via Discord
- File Watcher: Monitor landing folder for new transcripts
- Direct Processing: Process a transcript file directly

Usage:
    python main.py bot          # Start the Discord bot
    python main.py watch        # Start the file watcher
    python main.py process FILE # Process a specific transcript file
    python main.py help         # Show this help message
"""

import sys
import asyncio
from pathlib import Path


def show_help():
    """Display help information."""
    print("""
Secretary AI - Meeting Transcript Integration System
=====================================================

A Discord/Messenger AI bot that processes meeting transcripts,
extracts key information, and stores it in a database.

COMMANDS
--------

  python main.py bot
      Start the Discord bot. The bot responds when mentioned and
      provides slash commands for transcript processing.

  python main.py watch
      Start the file watcher. Monitors the landing folder for new
      transcript files and provides interactive processing.

  python main.py process <file>
      Process a specific transcript file directly. Prompts for
      meeting name and type interactively.

  python main.py setup
      Run database setup to ensure all tables exist.

  python main.py help
      Show this help message.

FOLDER STRUCTURE
----------------

  landing/              - Drop transcript files here
    executive/          - Executive committee meetings
    projects_subcommittee/
    events_subcommittee/
    sponsorships_subcommittee/
    marketing_subcommittee/
    content-creation_subcommittee/
    hr_subcommittee/
    full/               - Full committee meetings
    unscheduled/        - Ad-hoc meetings

DISCORD COMMANDS
----------------

  /process_transcript   - Process a transcript file
  /list_transcripts     - List available transcript files
  /meeting_stats        - View meeting statistics
  /start_watcher        - Info about the file watcher

  @bot <message>        - Chat with the AI assistant

ENVIRONMENT VARIABLES
---------------------

  DISCORD_TOKEN         - Discord bot token (required)
  OPENAI_API_KEY        - OpenAI API key (required)
  DATABASE_URL          - PostgreSQL connection URL (required)
  OPENAI_MODEL          - Model to use (default: gpt-4.1-mini)
  DISCORD_PROXY         - Optional proxy for Discord connection

For more information, see the README.md file.
""")


async def run_bot():
    """Start the Discord bot."""
    print("Starting Discord bot...")
    
    # Import here to avoid loading everything for help/other commands
    from discord_bot.bot import create_bot, TOKEN, DISCORD_PROXY_NORMALIZED
    
    try:
        import certifi
        import os
        import ssl
        from aiohttp_socks import ProxyConnector
        
        connector = None
        proxy = None
        
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
            
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install -r requirements.txt")
        sys.exit(1)


def run_watcher():
    """Start the file watcher."""
    print("Starting file watcher...")
    
    from transcript_integrator.file_watcher import FileWatcher, get_landing_directory
    
    landing_dir = get_landing_directory()
    
    # Ensure landing directory exists with subfolders
    if not landing_dir.exists():
        print(f"Creating landing directory: {landing_dir}")
        landing_dir.mkdir(parents=True, exist_ok=True)
        
        subfolders = [
            'executive',
            'projects_subcommittee',
            'events_subcommittee',
            'sponsorships_subcommittee',
            'marketing_subcommittee',
            'content-creation_subcommittee',
            'hr_subcommittee',
            'full',
            'unscheduled',
        ]
        for folder in subfolders:
            (landing_dir / folder).mkdir(exist_ok=True)
    
    watcher = FileWatcher(str(landing_dir))
    watcher.run()


async def process_file(file_path: str):
    """Process a specific transcript file."""
    from transcript_integrator.integrator import TranscriptIntegrator, MEETING_TYPES
    
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    
    print(f"\nProcessing: {path}")
    print("-" * 50)
    
    # Get meeting info
    meeting_name = input("Enter meeting name: ").strip()
    if not meeting_name:
        print("Error: Meeting name is required")
        sys.exit(1)
    
    print(f"\nMeeting types: {', '.join(MEETING_TYPES)}")
    meeting_type = input("Enter meeting type: ").strip().lower()
    if meeting_type not in MEETING_TYPES:
        print(f"Error: Invalid meeting type")
        sys.exit(1)
    
    # Process
    integrator = TranscriptIntegrator()
    
    try:
        await integrator.setup()
        
        result = await integrator.process_transcript(
            transcript_path=str(path),
            meeting_name=meeting_name,
            meeting_type=meeting_type,
        )
        
        print("\n" + "=" * 50)
        print("PROCESSING COMPLETE")
        print("=" * 50)
        print(f"Meeting ID: {result['meeting_id']}")
        print(f"Members: {result['members_identified']}")
        print(f"Projects: {result['projects_linked']}")
        print(f"Topics: {result['topics_linked']} ({result['new_topics_created']} new)")
        print(f"Tasks: {result['tasks_created']}")
        print("=" * 50)
        
    finally:
        await integrator.close()


async def run_setup():
    """Run database setup."""
    print("Setting up database tables...")
    
    from transcript_integrator.models import Base
    from transcript_integrator.integrator import TranscriptIntegrator
    
    integrator = TranscriptIntegrator()
    
    try:
        # Create tables
        async with integrator.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        print("Database tables created/verified successfully.")
        
        # Load and display stats
        await integrator.setup()
        print(f"\nCurrent data:")
        print(f"  - {len(integrator.committee_members)} committee members")
        print(f"  - {len(integrator.projects)} projects")
        print(f"  - {len(integrator.topics)} topics")
        
    finally:
        await integrator.close()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == 'help':
        show_help()
    
    elif command == 'bot':
        asyncio.run(run_bot())
    
    elif command == 'watch':
        run_watcher()
    
    elif command == 'process':
        if len(sys.argv) < 3:
            print("Error: Please provide a file path")
            print("Usage: python main.py process <file>")
            sys.exit(1)
        asyncio.run(process_file(sys.argv[2]))
    
    elif command == 'setup':
        asyncio.run(run_setup())
    
    else:
        print(f"Unknown command: {command}")
        print("Run 'python main.py help' for usage information.")
        sys.exit(1)


if __name__ == "__main__":
    main()
