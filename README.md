# Secretary AI

An AI-powered Discord bot and meeting transcript integration system for business information management.

## Features

- **Meeting Transcript Processing**: Automatically extract participants, projects, topics, tasks, and generate summaries from meeting transcripts using GPT-4.1-mini
- **Task Extraction**: Detect and record explicitly assigned tasks with deadlines and assignees
- **Fuzzy Matching**: Intelligently match extracted names to existing database records
- **File Watcher**: Monitor a landing folder for new transcripts with interactive renaming
- **Discord Integration**: Chat with AI and manage transcripts via Discord slash commands
- **Async Architecture**: Built for performance with async database operations and API calls

## Quick Start

### 1. Install Dependencies

```bash
# Using pip
pip install -r requirements.txt

# Or using uv
uv pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required environment variables:
- `DISCORD_TOKEN` - Your Discord bot token
- `OPENAI_API_KEY` - Your OpenAI API key
- `DATABASE_URL` - PostgreSQL connection string

### 3. Run the Bot

```bash
# Start Discord bot
python main.py bot

# Or start file watcher
python main.py watch

# Or process a file directly
python main.py process landing/my_transcript.txt
```

## Commands

### CLI Commands

```bash
python main.py bot          # Start the Discord bot
python main.py watch        # Start the file watcher
python main.py process FILE # Process a specific transcript
python main.py setup        # Create/verify database tables
python main.py help         # Show help
```

### Discord Slash Commands

| Command | Description |
|---------|-------------|
| `/process_transcript` | Process a transcript file from the landing folder |
| `/list_transcripts` | List available transcript files |
| `/meeting_stats` | View statistics about processed meetings |
| `/start_watcher` | Information about running the file watcher |

Mention the bot to chat: `@SecretaryAI how do I add a new project?`

## Project Structure

```
secretary-ai/
├── main.py                    # Main entry point
├── discord_bot/
│   └── bot.py                 # Discord bot with slash commands
├── transcript_integrator/
│   ├── __init__.py
│   ├── integrator.py          # Main transcript processing engine
│   ├── models.py              # SQLAlchemy database models
│   └── file_watcher.py        # File monitoring and renaming
├── landing/                   # Drop transcript files here
│   ├── executive/
│   ├── projects_subcommittee/
│   ├── events_subcommittee/
│   ├── sponsorships_subcommittee/
│   ├── marketing_subcommittee/
│   ├── content-creation_subcommittee/
│   ├── hr_subcommittee/
│   ├── full/
│   └── unscheduled/
├── database-erd.txt           # Database schema reference
├── requirements.txt
├── pyproject.toml
└── .env                       # Environment configuration
```

## Database Schema

The system uses the following tables:

| Table | Description |
|-------|-------------|
| `committee` | Organization members with Discord IDs and roles |
| `meeting` | Meeting records with summaries |
| `meeting_members` | Links meetings to attendees |
| `meeting_projects` | Links meetings to discussed projects |
| `meeting_topics` | Links meetings to discussion topics |
| `meeting_tasks` | Links meetings to assigned tasks |
| `projects` | Project information |
| `project_members` | Links projects to team members |
| `tasks` | Task records with deadlines |
| `task_members` | Links tasks to assignees |
| `topic` | Discussion topics |

## Meeting Types

The system supports the following meeting types:

- `executive` - Executive Committee Meeting
- `projects_subcommittee` - Projects Subcommittee Meeting
- `events_subcommittee` - Events Subcommittee Meeting
- `sponsorships_subcommittee` - Sponsorships Subcommittee Meeting
- `marketing_subcommittee` - Marketing Subcommittee Meeting
- `content-creation_subcommittee` - Content Creation Subcommittee Meeting
- `hr_subcommittee` - HR Subcommittee Meeting
- `full` - Full Committee Meeting
- `unscheduled` - Unscheduled / Ad-hoc Meeting

## How It Works

### File Watcher Flow

1. Drop a transcript file (`.txt`) into the `landing/` folder
2. The watcher detects the new file and prompts you:
   - Select meeting type
   - Enter meeting date (DD-MM-YYYY)
   - Enter meeting name
   - Choose destination subfolder
3. File is renamed with `INGESTED_` prefix and moved to the selected folder
4. Optionally run AI analysis to extract meeting information

### Transcript Processing

1. **Member Extraction**: Identifies participants from the transcript and matches them to committee members using fuzzy matching
2. **Project Linking**: Detects project mentions and links them to the meeting
3. **Topic Identification**: Extracts discussion topics, creating new ones if needed
4. **Task Detection**: Finds explicitly assigned tasks with deadlines and assignees
5. **Summary Generation**: Creates a comprehensive meeting summary

### Fuzzy Matching

The system uses Python's `difflib.get_close_matches()` to handle:
- Typos and misspellings
- Name variations (plural/singular)
- Case differences

Default cutoffs:
- Members: 70% similarity
- Projects: 60% similarity
- Topics: 70% similarity

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_TOKEN` | Yes | - | Discord bot token |
| `OPENAI_API_KEY` | Yes | - | OpenAI API key |
| `DATABASE_URL` | Yes | - | PostgreSQL connection URL |
| `OPENAI_MODEL` | No | `gpt-4.1-mini` | OpenAI model to use |
| `DISCORD_PROXY` | No | - | Proxy for Discord connection |

### Example .env

```env
DISCORD_TOKEN=your_discord_token_here
DATABASE_URL=postgresql://user:password@host:5432/database
OPENAI_API_KEY=sk-your-openai-key-here
OPENAI_MODEL=gpt-4.1-mini
# DISCORD_PROXY=socks5://127.0.0.1:7898
```

## Development

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
# Using black
black .

# Using ruff
ruff check --fix .
```

## Troubleshooting

### "No match found for member: X"

The member name in the transcript doesn't closely match any names in the `committee` table. Either:
- Add the member to the database
- Use a name that more closely matches existing records

### "asyncpg.exceptions.UndefinedTableError"

The database tables don't exist. Run:
```bash
python main.py setup
```

### Discord bot not responding

1. Check that `DISCORD_TOKEN` is set correctly
2. Ensure the bot has been invited to your server with proper permissions
3. Enable "Message Content Intent" in Discord Developer Portal
4. If behind a firewall, set `DISCORD_PROXY`

## License

MIT License
