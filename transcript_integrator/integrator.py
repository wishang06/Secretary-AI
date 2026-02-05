"""
Transcript Integrator Engine

Uses GPT-4.1-mini to extract structured information from meeting transcripts:
- Meeting participants (fuzzy matched to existing members)
- Related projects (fuzzy matched to existing projects)
- Topics discussed (fuzzy matched, creates new if needed)
- Tasks assigned (with deadlines and assignees)
- Meeting summary

All operations are async for performance.
"""

import os
import re
import json
import difflib
import logging
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from sqlalchemy.sql import func

from .models import (
    Base,
    Committee,
    Meeting,
    MeetingMembers,
    MeetingProjects,
    MeetingTopics,
    MeetingTasks,
    Project,
    ProjectMembers,
    Task,
    TaskMembers,
    Topic,
)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('transcript_integrator.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')

# Ensure the DATABASE_URL uses an async driver (asyncpg for PostgreSQL)
if DATABASE_URL:
    if DATABASE_URL.startswith('postgresql://'):
        DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)
    elif DATABASE_URL.startswith('postgresql+psycopg2://'):
        DATABASE_URL = DATABASE_URL.replace('postgresql+psycopg2://', 'postgresql+asyncpg://', 1)

# Meeting type options
MEETING_TYPES = [
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


class TranscriptIntegrator:
    """
    Main engine for processing meeting transcripts and integrating with database.
    """
    
    def __init__(self):
        """Initialize the transcript integrator with database and OpenAI connections."""
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL not found in environment variables.")
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables.")
        
        # Database setup
        self.engine = create_async_engine(DATABASE_URL, echo=False, future=True)
        self.async_session = sessionmaker(
            self.engine, 
            expire_on_commit=False, 
            class_=AsyncSession
        )
        
        # OpenAI client
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.model = OPENAI_MODEL
        
        # Context caches (loaded from database)
        self.committee_members: Dict[str, Dict[str, Any]] = {}
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.topics: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"TranscriptIntegrator initialized with model: {self.model}")
    
    async def setup(self) -> None:
        """Load all context information from the database."""
        logger.info("Loading context from database...")
        self.committee_members = await self._load_committee_members()
        self.projects = await self._load_projects()
        self.topics = await self._load_topics()
        logger.info(
            f"Loaded {len(self.committee_members)} members, "
            f"{len(self.projects)} projects, "
            f"{len(self.topics)} topics"
        )
    
    async def _load_committee_members(self) -> Dict[str, Dict[str, Any]]:
        """Load committee members from database."""
        members = {}
        async with self.async_session() as session:
            result = await session.execute(
                select(Committee.member_id, Committee.member_name, Committee.subcommittee, Committee.role)
            )
            for member_id, name, subcommittee, role in result.fetchall():
                if name:
                    members[name.lower()] = {
                        'id': member_id,
                        'name': name,
                        'subcommittee': subcommittee,
                        'role': role
                    }
        return members
    
    async def _load_projects(self) -> Dict[str, Dict[str, Any]]:
        """Load projects from database."""
        projects = {}
        async with self.async_session() as session:
            result = await session.execute(
                select(Project.project_id, Project.project_name, Project.project_description)
            )
            for project_id, name, description in result.fetchall():
                if name:
                    projects[name.lower()] = {
                        'id': project_id,
                        'name': name,
                        'description': description or ''
                    }
        return projects
    
    async def _load_topics(self) -> Dict[str, Dict[str, Any]]:
        """Load topics from database."""
        topics = {}
        async with self.async_session() as session:
            result = await session.execute(
                select(Topic.topic_id, Topic.topic_name, Topic.topic_description)
            )
            for topic_id, name, description in result.fetchall():
                if name:
                    topics[name.lower()] = {
                        'id': topic_id,
                        'name': name,
                        'description': description or ''
                    }
        return topics
    
    async def process_transcript(
        self,
        transcript_path: str,
        meeting_name: str,
        meeting_type: str,
        meeting_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Process a transcript file and integrate all extracted information into the database.
        
        Args:
            transcript_path: Path to the transcript text file
            meeting_name: Name/title of the meeting
            meeting_type: Type of meeting (executive, subcommittee, full, unscheduled)
            meeting_date: Optional meeting date (defaults to current date)
        
        Returns:
            Dictionary with processing results and statistics
        """
        logger.info(f"Processing transcript: {transcript_path}")
        
        # Read transcript content
        transcript_content = self._read_transcript(transcript_path)
        if not transcript_content:
            raise ValueError(f"Could not read transcript from {transcript_path}")
        
        # Set meeting date
        if meeting_date is None:
            meeting_date = datetime.now()
        
        # Extract all information using LLM
        logger.info("Extracting meeting information with LLM...")
        
        # Extract members and projects
        members_projects = await self._extract_members_and_projects(
            transcript_content, meeting_type
        )
        
        # Extract topics
        topics_data = await self._extract_topics(transcript_content, meeting_type)
        
        # Extract tasks
        tasks_data = await self._extract_tasks(transcript_content, meeting_type)
        
        # Generate summary
        summary = await self._generate_summary(transcript_content, meeting_type)
        
        # Process and match extracted data
        matched_members = self._match_members(members_projects.get('member_names', []))
        matched_projects = self._match_projects(members_projects.get('project_names', []))
        processed_topics, new_topics_count = await self._process_topics(topics_data)
        processed_tasks, new_tasks_count = await self._process_tasks(tasks_data, matched_members)
        
        # Insert everything into database
        result = await self._insert_into_database(
            meeting_name=meeting_name,
            meeting_type=meeting_type,
            meeting_summary=summary,
            member_ids=[m['id'] for m in matched_members],
            project_ids=[p['id'] for p in matched_projects],
            topic_ids=[t['topic_id'] for t in processed_topics],
            task_data=processed_tasks
        )
        
        # Prepare result summary
        return {
            'success': True,
            'meeting_id': result['meeting_id'],
            'meeting_name': meeting_name,
            'meeting_type': meeting_type,
            'summary_length': len(summary) if summary else 0,
            'members_identified': len(matched_members),
            'member_names': [m['name'] for m in matched_members],
            'projects_linked': len(matched_projects),
            'project_names': [p['name'] for p in matched_projects],
            'topics_linked': len(processed_topics),
            'topic_names': [t['topic_name'] for t in processed_topics],
            'new_topics_created': new_topics_count,
            'tasks_created': len(processed_tasks),
            'task_names': [t['task_name'] for t in processed_tasks],
        }
    
    def _read_transcript(self, path: str) -> str:
        """Read transcript content from file."""
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading transcript: {e}")
            return ""
    
    async def _call_llm(self, prompt: str) -> str:
        """Make an async call to the LLM."""
        try:
            response = await self.openai_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,  # Low temperature for consistent extraction
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return ""
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling common formatting issues."""
        # Clean up the response
        content = response.strip()
        
        # Remove markdown code blocks if present
        if content.startswith('```json'):
            content = content[7:]
        elif content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        content = content.strip()
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Response content: {content[:500]}...")
            return {}
    
    async def _extract_members_and_projects(
        self, 
        transcript: str, 
        meeting_type: str
    ) -> Dict[str, List[str]]:
        """Extract member names and project names from transcript."""
        
        # Format context
        members_context = "\n".join([
            f"- {m['name']} ({m.get('role', 'Member')}, {m.get('subcommittee', 'N/A')})" 
            for m in self.committee_members.values()
        ])
        projects_context = "\n".join([
            f"- {p['name']}: {p.get('description', 'No description')[:100]}" 
            for p in self.projects.values()
        ])
        
        prompt = f"""You are an expert at analyzing meeting transcripts and extracting structured information.

Available committee members:
{members_context}

Available projects and their descriptions:
{projects_context}

This is a {meeting_type} meeting. Analyze the transcript and extract:
1. List of committee members who participated (match names to the available list above)
2. List of projects that were discussed or are relevant to this meeting

Guidelines:
- For member names, match as closely as possible to the available list
- For projects, identify any projects mentioned directly or by context
- Be inclusive - if someone seems to have participated, include them

Transcript:
{transcript}

Return your response in this exact JSON format:
{{
    "member_names": ["Name1", "Name2"],
    "project_names": ["Project1", "Project2"]
}}"""
        
        response = await self._call_llm(prompt)
        return self._parse_json_response(response)
    
    async def _extract_topics(
        self, 
        transcript: str, 
        meeting_type: str
    ) -> List[Dict[str, Any]]:
        """Extract discussion topics from transcript."""
        
        # Format existing topics context
        topics_context = "\n".join([
            f"- {t['name']}" for t in self.topics.values()
        ]) if self.topics else "No existing topics"
        
        prompt = f"""You are an expert at analyzing meeting transcripts and extracting key discussion topics.

Existing topics in our system:
{topics_context}

This is a {meeting_type} meeting. Analyze the transcript and identify the key topics discussed.

For each topic:
1. If it matches or is very similar to an existing topic, use the EXACT name from the existing list
2. If it's a completely new topic, suggest a clear, concise name
3. Provide a brief summary of how this topic was discussed

Guidelines:
- Focus on substantial topics with meaningful discussion
- Group related discussions under broader topics
- Aim for 3-8 main topics per meeting
- Don't be overly granular

Transcript:
{transcript}

Return your response in this exact JSON format:
{{
    "topics": [
        {{
            "topic_name": "Topic Name",
            "topic_summary": "Brief summary of the discussion",
            "is_existing": true
        }}
    ]
}}"""
        
        response = await self._call_llm(prompt)
        data = self._parse_json_response(response)
        return data.get('topics', [])
    
    async def _extract_tasks(
        self, 
        transcript: str, 
        meeting_type: str
    ) -> List[Dict[str, Any]]:
        """Extract explicitly assigned tasks from transcript."""
        
        # Format members context for task assignment matching
        members_context = "\n".join([
            f"- {m['name']}" for m in self.committee_members.values()
        ])
        
        prompt = f"""You are an expert at analyzing meeting transcripts and extracting task assignments.

Available committee members:
{members_context}

This is a {meeting_type} meeting. Analyze the transcript and extract ONLY EXPLICITLY ASSIGNED TASKS.

A task is explicitly assigned when:
- Someone says "X will do Y" or "X is assigned to Y"
- Someone says "X, can you handle Y?" and X agrees
- Someone says "X, you're responsible for Y"
- A clear action item is assigned to a specific person

DO NOT include:
- General discussion points
- Ideas or suggestions without clear assignment
- Vague mentions of things that need to be done without assignees

For each task, extract:
1. task_name: A clear, concise name for the task
2. task_description: More detail about what needs to be done
3. deadline: If a deadline is mentioned (date in YYYY-MM-DD format), otherwise null
4. assigned_to: List of member names assigned (match to available list above)

Transcript:
{transcript}

Return your response in this exact JSON format:
{{
    "tasks": [
        {{
            "task_name": "Task Name",
            "task_description": "Description of what needs to be done",
            "deadline": "YYYY-MM-DD or null",
            "assigned_to": ["Member Name 1", "Member Name 2"]
        }}
    ]
}}"""
        
        response = await self._call_llm(prompt)
        data = self._parse_json_response(response)
        return data.get('tasks', [])
    
    async def _generate_summary(self, transcript: str, meeting_type: str) -> str:
        """Generate a comprehensive meeting summary."""
        
        # Format context
        projects_context = "\n".join([
            f"- {p['name']}: {p.get('description', 'No description')[:100]}" 
            for p in self.projects.values()
        ])
        members_context = "\n".join([
            f"- {m['name']} ({m.get('role', 'Member')})" 
            for m in self.committee_members.values()
        ])
        
        prompt = f"""You are an expert meeting summarizer.

Available projects:
{projects_context}

Available committee members:
{members_context}

This is a {meeting_type} meeting. Create a comprehensive summary that:
1. Identifies the main topics discussed
2. Lists key decisions made
3. Mentions action items and next steps
4. Relates discussions to relevant projects when possible
5. Notes important deadlines or milestones mentioned

Transcript:
{transcript}

Write a clear, structured summary (2-4 paragraphs) that captures the essential information:"""
        
        response = await self._call_llm(prompt)
        return response.strip()
    
    def _match_members(self, names: List[str]) -> List[Dict[str, Any]]:
        """Match extracted member names to database records using fuzzy matching."""
        matched = []
        
        for name in names:
            key = name.lower()
            
            # Try exact match first
            if key in self.committee_members:
                matched.append(self.committee_members[key])
                logger.debug(f"Exact match for member: {name}")
                continue
            
            # Try fuzzy matching
            matches = difflib.get_close_matches(
                key, 
                self.committee_members.keys(), 
                n=1, 
                cutoff=0.7
            )
            if matches:
                matched_key = matches[0]
                matched.append(self.committee_members[matched_key])
                logger.info(f"Fuzzy matched member: '{name}' -> '{self.committee_members[matched_key]['name']}'")
            else:
                logger.warning(f"No match found for member: {name}")
        
        return matched
    
    def _match_projects(self, names: List[str]) -> List[Dict[str, Any]]:
        """Match extracted project names to database records using fuzzy matching."""
        matched = []
        
        for name in names:
            key = name.lower()
            
            # Try exact match first
            if key in self.projects:
                matched.append(self.projects[key])
                logger.debug(f"Exact match for project: {name}")
                continue
            
            # Try fuzzy matching
            matches = difflib.get_close_matches(
                key, 
                self.projects.keys(), 
                n=1, 
                cutoff=0.6  # Slightly lower threshold for projects
            )
            if matches:
                matched_key = matches[0]
                matched.append(self.projects[matched_key])
                logger.info(f"Fuzzy matched project: '{name}' -> '{self.projects[matched_key]['name']}'")
            else:
                logger.warning(f"No match found for project: {name}")
        
        return matched
    
    async def _process_topics(
        self, 
        topics_data: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Process identified topics, matching existing ones or creating new ones.
        Returns (processed_topics, new_topics_count).
        """
        processed = []
        new_count = 0
        
        async with self.async_session() as session:
            async with session.begin():
                for topic in topics_data:
                    topic_name = topic.get('topic_name', '').strip()
                    topic_summary = topic.get('topic_summary', '').strip()
                    
                    if not topic_name:
                        continue
                    
                    key = topic_name.lower()
                    topic_id = None
                    matched_name = topic_name
                    
                    # Try exact match
                    if key in self.topics:
                        topic_id = self.topics[key]['id']
                        matched_name = self.topics[key]['name']
                        logger.debug(f"Exact match for topic: {topic_name}")
                    else:
                        # Try fuzzy matching
                        matches = difflib.get_close_matches(
                            key, 
                            self.topics.keys(), 
                            n=1, 
                            cutoff=0.7
                        )
                        
                        if matches:
                            matched_key = matches[0]
                            topic_id = self.topics[matched_key]['id']
                            matched_name = self.topics[matched_key]['name']
                            logger.info(f"Fuzzy matched topic: '{topic_name}' -> '{matched_name}'")
                        else:
                            # Create new topic
                            logger.info(f"Creating new topic: '{topic_name}'")
                            new_topic = Topic(
                                topic_name=topic_name,
                                topic_description=topic_summary,
                            )
                            session.add(new_topic)
                            await session.flush()
                            topic_id = new_topic.topic_id
                            
                            # Update cache
                            self.topics[key] = {
                                'id': topic_id,
                                'name': topic_name,
                                'description': topic_summary
                            }
                            new_count += 1
                    
                    processed.append({
                        'topic_id': topic_id,
                        'topic_name': matched_name,
                        'topic_summary': topic_summary
                    })
                
                await session.commit()
        
        return processed, new_count
    
    async def _process_tasks(
        self, 
        tasks_data: List[Dict[str, Any]],
        matched_members: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Process extracted tasks and create task records.
        Returns (processed_tasks, new_tasks_count).
        """
        processed = []
        
        # Create a lookup for matched members by name
        member_lookup = {m['name'].lower(): m for m in matched_members}
        # Also add from our full cache
        for key, m in self.committee_members.items():
            member_lookup[key] = m
        
        async with self.async_session() as session:
            async with session.begin():
                for task in tasks_data:
                    task_name = task.get('task_name', '').strip()
                    task_description = task.get('task_description', '').strip()
                    deadline_str = task.get('deadline')
                    assigned_to = task.get('assigned_to', [])
                    
                    if not task_name:
                        continue
                    
                    # Parse deadline if provided
                    task_deadline = None
                    if deadline_str and deadline_str != 'null':
                        try:
                            task_deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
                        except ValueError:
                            logger.warning(f"Could not parse deadline: {deadline_str}")
                    
                    # Match assignees
                    assignee_ids = []
                    assignee_names = []
                    for assignee in assigned_to:
                        assignee_key = assignee.lower()
                        
                        # Try exact match
                        if assignee_key in member_lookup:
                            assignee_ids.append(member_lookup[assignee_key]['id'])
                            assignee_names.append(member_lookup[assignee_key]['name'])
                        else:
                            # Try fuzzy match
                            matches = difflib.get_close_matches(
                                assignee_key,
                                member_lookup.keys(),
                                n=1,
                                cutoff=0.7
                            )
                            if matches:
                                matched_key = matches[0]
                                assignee_ids.append(member_lookup[matched_key]['id'])
                                assignee_names.append(member_lookup[matched_key]['name'])
                                logger.info(f"Fuzzy matched task assignee: '{assignee}' -> '{member_lookup[matched_key]['name']}'")
                            else:
                                logger.warning(f"No match found for task assignee: {assignee}")
                    
                    # Create task
                    new_task = Task(
                        task_name=task_name,
                        task_description=task_description,
                        task_deadline=task_deadline,
                    )
                    session.add(new_task)
                    await session.flush()
                    
                    logger.info(f"Created task: '{task_name}' assigned to {assignee_names}")
                    
                    processed.append({
                        'task_id': new_task.task_id,
                        'task_name': task_name,
                        'task_description': task_description,
                        'deadline': task_deadline,
                        'assignee_ids': assignee_ids,
                        'assignee_names': assignee_names
                    })
                
                await session.commit()
        
        return processed, len(processed)
    
    async def _insert_into_database(
        self,
        meeting_name: str,
        meeting_type: str,
        meeting_summary: str,
        member_ids: List[int],
        project_ids: List[int],
        topic_ids: List[int],
        task_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Insert all meeting data into the database."""
        
        async with self.async_session() as session:
            async with session.begin():
                # Create meeting record
                meeting = Meeting(
                    meeting_name=meeting_name,
                    meeting_type=meeting_type,
                    meeting_summary=meeting_summary,
                )
                session.add(meeting)
                await session.flush()
                
                meeting_id = meeting.meeting_id
                logger.info(f"Created meeting with ID: {meeting_id}")
                
                # Insert meeting-member relationships
                for member_id in set(member_ids):  # Use set to avoid duplicates
                    session.add(MeetingMembers(
                        meeting_id=meeting_id,
                        member_id=member_id,
                    ))
                
                # Insert meeting-project relationships
                for project_id in set(project_ids):
                    session.add(MeetingProjects(
                        meeting_id=meeting_id,
                        project_id=project_id,
                    ))
                
                # Insert meeting-topic relationships
                for topic_id in set(topic_ids):
                    session.add(MeetingTopics(
                        meeting_id=meeting_id,
                        topic_id=topic_id,
                    ))
                
                # Insert meeting-task relationships and task-member relationships
                for task in task_data:
                    task_id = task['task_id']
                    
                    # Link task to meeting
                    session.add(MeetingTasks(
                        meeting_id=meeting_id,
                        task_id=task_id,
                    ))
                    
                    # Link task to assigned members
                    for assignee_id in task.get('assignee_ids', []):
                        session.add(TaskMembers(
                            task_id=task_id,
                            member_id=assignee_id,
                        ))
                
                await session.commit()
        
        return {'meeting_id': meeting_id}
    
    async def close(self) -> None:
        """Close database connections."""
        await self.engine.dispose()
        logger.info("TranscriptIntegrator closed")


# CLI interface for standalone usage
async def main():
    """Main function for CLI usage."""
    import sys
    
    print("=" * 60)
    print("Transcript Integrator - Standalone Mode")
    print("=" * 60)
    
    if len(sys.argv) < 2:
        print("\nUsage: python -m transcript_integrator.integrator <transcript_path>")
        print("\nExample:")
        print("  python -m transcript_integrator.integrator landing/meeting.txt")
        return
    
    transcript_path = sys.argv[1]
    
    if not os.path.exists(transcript_path):
        print(f"Error: File not found: {transcript_path}")
        return
    
    # Get meeting info from user
    print(f"\nProcessing: {transcript_path}")
    print("-" * 40)
    
    meeting_name = input("Enter meeting name: ").strip()
    if not meeting_name:
        print("Error: Meeting name is required")
        return
    
    print(f"\nMeeting types: {', '.join(MEETING_TYPES)}")
    meeting_type = input("Enter meeting type: ").strip().lower()
    if meeting_type not in MEETING_TYPES:
        print(f"Error: Invalid meeting type. Must be one of: {MEETING_TYPES}")
        return
    
    # Initialize and run
    integrator = TranscriptIntegrator()
    
    try:
        await integrator.setup()
        
        result = await integrator.process_transcript(
            transcript_path=transcript_path,
            meeting_name=meeting_name,
            meeting_type=meeting_type,
        )
        
        print("\n" + "=" * 60)
        print("INTEGRATION COMPLETE")
        print("=" * 60)
        print(f"Meeting ID: {result['meeting_id']}")
        print(f"Meeting Name: {result['meeting_name']}")
        print(f"Meeting Type: {result['meeting_type']}")
        print(f"Summary Length: {result['summary_length']} characters")
        print(f"\nMembers Identified: {result['members_identified']}")
        if result['member_names']:
            print(f"  - {', '.join(result['member_names'])}")
        print(f"\nProjects Linked: {result['projects_linked']}")
        if result['project_names']:
            print(f"  - {', '.join(result['project_names'])}")
        print(f"\nTopics Linked: {result['topics_linked']} ({result['new_topics_created']} new)")
        if result['topic_names']:
            print(f"  - {', '.join(result['topic_names'])}")
        print(f"\nTasks Created: {result['tasks_created']}")
        if result['task_names']:
            for task_name in result['task_names']:
                print(f"  - {task_name}")
        
    except Exception as e:
        print(f"\nError: {e}")
        logger.error(f"Processing failed: {e}", exc_info=True)
    finally:
        await integrator.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
