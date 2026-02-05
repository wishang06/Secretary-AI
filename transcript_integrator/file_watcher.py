"""
File Watcher for Transcript Integration

Monitors a landing folder for new transcript files and provides:
- Interactive file renaming with meeting metadata
- Automatic file organization into subfolders
- Integration with transcript processing engine

Meeting types supported:
- executive
- [group]_subcommittee (projects, events, sponsorships, marketing, content-creation, hr)
- full
- unscheduled
"""

import os
import re
import time
import shutil
import asyncio
import logging
import threading
import queue
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('file_watcher.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Meeting type options
MEETING_TYPES = {
    '1': ('executive', 'Executive Committee Meeting'),
    '2': ('projects_subcommittee', 'Projects Subcommittee Meeting'),
    '3': ('events_subcommittee', 'Events Subcommittee Meeting'),
    '4': ('sponsorships_subcommittee', 'Sponsorships Subcommittee Meeting'),
    '5': ('marketing_subcommittee', 'Marketing Subcommittee Meeting'),
    '6': ('content-creation_subcommittee', 'Content Creation Subcommittee Meeting'),
    '7': ('hr_subcommittee', 'HR Subcommittee Meeting'),
    '8': ('full', 'Full Committee Meeting'),
    '9': ('unscheduled', 'Unscheduled / Ad-hoc Meeting'),
}


class FileWatcherHandler(FileSystemEventHandler):
    """Handler for file system events with interactive renaming."""
    
    def __init__(self, watch_directory: Path, integrator=None):
        """
        Initialize the file watcher handler.
        
        Args:
            watch_directory: Path to the landing directory
            integrator: Optional TranscriptIntegrator instance for processing
        """
        self.watch_directory = Path(watch_directory)
        self.integrator = integrator
        self.processed_files = set()  # Track files we've already prompted for
        
        logger.info(f"FileWatcher initialized for: {self.watch_directory}")
    
    def on_created(self, event):
        """Called when a file or directory is created."""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        
        # Skip hidden files, non-text files, and already processed files
        if file_path.name.startswith('.'):
            return
        if not file_path.suffix.lower() in ['.txt', '.md', '.text']:
            return
        if file_path.name.startswith('INGESTED_'):
            return
        if str(file_path) in self.processed_files:
            return
        
        # Check if file is in a subfolder (already organized)
        try:
            relative = file_path.relative_to(self.watch_directory)
            if len(relative.parts) > 1:
                # File is in a subfolder, skip
                return
        except ValueError:
            return
        
        self.processed_files.add(str(file_path))
        
        logger.info(f"New file detected: {file_path.name}")
        print(f"\n{'='*60}")
        print("NEW TRANSCRIPT FILE DETECTED")
        print(f"{'='*60}")
        print(f"File: {file_path.name}")
        print(f"Path: {file_path}")
        print(f"Size: {self._get_file_size(file_path)}")
        print(f"Time: {self._get_file_time(file_path)}")
        print(f"{'='*60}")
        
        # Process the new file
        self._process_new_file(file_path)
    
    def on_moved(self, event):
        """Called when a file is moved/renamed."""
        if event.is_directory:
            return
        
        src_path = Path(event.src_path)
        dest_path = Path(event.dest_path)
        
        logger.info(f"File moved: {src_path.name} -> {dest_path.name}")
    
    def _get_file_size(self, file_path: Path) -> str:
        """Get human-readable file size."""
        try:
            size = file_path.stat().st_size
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    return f"{size:.1f} {unit}"
                size /= 1024.0
            return f"{size:.1f} TB"
        except Exception:
            return "Unknown"
    
    def _get_file_time(self, file_path: Path) -> str:
        """Get file modification time."""
        try:
            mtime = file_path.stat().st_mtime
            return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
        except Exception:
            return "Unknown"
    
    def _process_new_file(self, file_path: Path):
        """Process a newly detected file with interactive renaming."""
        try:
            print("\nLet's set up this transcript for processing:")
            print("-" * 50)
            
            # Step 1: Get meeting type
            meeting_type = self._get_meeting_type()
            if meeting_type is None:
                print("\nCancelled. File will not be processed.")
                return
            
            # Step 2: Get meeting date
            date_str = self._get_date()
            if date_str is None:
                print("\nCancelled. File will not be processed.")
                return
            
            # Step 3: Get meeting name
            meeting_name = self._get_meeting_name()
            if meeting_name is None:
                print("\nCancelled. File will not be processed.")
                return
            
            # Step 4: Choose destination subfolder
            destination_folder = self._get_destination_folder(meeting_type)
            if destination_folder is None:
                print("\nCancelled. File will not be processed.")
                return
            
            # Construct new filename
            new_filename = f"INGESTED_{meeting_type}_{date_str}_{meeting_name}.txt"
            destination_path = self.watch_directory / destination_folder / new_filename
            
            # Confirm with user
            print(f"\n{'='*50}")
            print("SUMMARY")
            print(f"{'='*50}")
            print(f"Meeting Type: {meeting_type}")
            print(f"Meeting Date: {date_str}")
            print(f"Meeting Name: {meeting_name}")
            print(f"New Filename: {new_filename}")
            print(f"Destination:  {destination_folder}/")
            print(f"{'='*50}")
            
            confirm = input("\nProceed with this configuration? (Y/n): ").strip().lower()
            if confirm not in ['', 'y', 'yes']:
                print("Cancelled. Starting over...")
                return self._process_new_file(file_path)
            
            # Create destination directory if needed
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy file to destination
            shutil.copy2(file_path, destination_path)
            print(f"\nFile copied to: {destination_path}")
            logger.info(f"File copied: {file_path} -> {destination_path}")
            
            # Ask about original file
            delete_original = input("\nDelete the original file? (y/N): ").strip().lower()
            if delete_original in ['y', 'yes']:
                file_path.unlink()
                print("Original file deleted.")
                logger.info(f"Original file deleted: {file_path}")
            else:
                print("Original file kept.")
            
            # Ask about transcript integration
            print(f"\n{'='*50}")
            print("TRANSCRIPT INTEGRATION")
            print(f"{'='*50}")
            print("Would you like to run AI analysis to extract:")
            print("  - Meeting participants")
            print("  - Related projects")
            print("  - Discussion topics")
            print("  - Assigned tasks")
            print("  - Meeting summary")
            
            run_integration = input("\nRun AI analysis? (Y/n): ").strip().lower()
            if run_integration in ['', 'y', 'yes']:
                self._run_transcript_integration(
                    destination_path, 
                    meeting_name, 
                    meeting_type
                )
            else:
                print("Skipping AI analysis. You can run it later using the CLI.")
            
            print(f"\n{'='*60}")
            print("FILE PROCESSING COMPLETE")
            print(f"{'='*60}\n")
            
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user.")
        except Exception as e:
            print(f"\nError processing file: {e}")
            logger.error(f"Error processing file {file_path}: {e}", exc_info=True)
    
    def _get_meeting_type(self) -> Optional[str]:
        """Get meeting type from user."""
        print("\n[1/4] SELECT MEETING TYPE")
        print("-" * 40)
        
        for key, (type_id, description) in MEETING_TYPES.items():
            print(f"  {key}. {description}")
        
        while True:
            choice = input("\nEnter number (1-9) or 'cancel': ").strip().lower()
            
            if choice in ['cancel', 'c', 'q', '']:
                return None
            
            if choice in MEETING_TYPES:
                meeting_type = MEETING_TYPES[choice][0]
                print(f"  Selected: {MEETING_TYPES[choice][1]}")
                return meeting_type
            
            print("  Invalid choice. Please enter a number 1-9.")
    
    def _get_date(self) -> Optional[str]:
        """Get meeting date from user."""
        print("\n[2/4] ENTER MEETING DATE")
        print("-" * 40)
        print("  Format: DD-MM-YYYY (e.g., 05-02-2026)")
        print("  Or type 'today' for today's date")
        
        while True:
            date_input = input("\nEnter date: ").strip()
            
            if date_input.lower() in ['cancel', 'c', 'q', '']:
                return None
            
            if date_input.lower() == 'today':
                date_str = datetime.now().strftime('%d-%m-%Y')
                print(f"  Using today's date: {date_str}")
                return date_str
            
            # Validate date format
            try:
                datetime.strptime(date_input, '%d-%m-%Y')
                print(f"  Date accepted: {date_input}")
                return date_input
            except ValueError:
                print("  Invalid format. Please use DD-MM-YYYY (e.g., 05-02-2026)")
    
    def _get_meeting_name(self) -> Optional[str]:
        """Get meeting name from user."""
        print("\n[3/4] ENTER MEETING NAME")
        print("-" * 40)
        print("  A descriptive name for this meeting")
        print("  Example: 'sprint_planning' or 'budget_review'")
        print("  (Spaces will be converted to underscores)")
        
        while True:
            name_input = input("\nEnter name: ").strip()
            
            if name_input.lower() in ['cancel', 'c', 'q', '']:
                return None
            
            if not name_input:
                print("  Please enter a name for the meeting.")
                continue
            
            # Clean the name
            cleaned = re.sub(r'[^\w\-]', '_', name_input.replace(' ', '_'))
            cleaned = re.sub(r'_+', '_', cleaned)  # Remove multiple underscores
            cleaned = cleaned.strip('_').lower()
            
            if cleaned:
                print(f"  Name accepted: {cleaned}")
                return cleaned
            
            print("  Invalid name. Please use letters, numbers, and underscores.")
    
    def _get_destination_folder(self, meeting_type: str) -> Optional[str]:
        """Get destination subfolder from user."""
        print("\n[4/4] SELECT DESTINATION FOLDER")
        print("-" * 40)
        
        # List available folders
        folders = []
        for item in sorted(self.watch_directory.iterdir()):
            if item.is_dir() and not item.name.startswith('.'):
                folders.append(item.name)
        
        if not folders:
            print("  No subfolders found. Using meeting type as folder.")
            return meeting_type
        
        # Find the suggested folder based on meeting type
        suggested = meeting_type if meeting_type in folders else folders[0]
        suggested_idx = folders.index(suggested) + 1 if suggested in folders else 1
        
        print(f"  Available folders:")
        for i, folder in enumerate(folders, 1):
            marker = " <-- suggested" if folder == suggested else ""
            print(f"    {i}. {folder}{marker}")
        
        while True:
            choice = input(f"\nEnter number (default: {suggested_idx}) or 'cancel': ").strip()
            
            if choice.lower() in ['cancel', 'c', 'q']:
                return None
            
            if choice == '':
                print(f"  Using: {suggested}")
                return suggested
            
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(folders):
                    print(f"  Selected: {folders[idx]}")
                    return folders[idx]
            except ValueError:
                pass
            
            print(f"  Invalid choice. Enter a number 1-{len(folders)}.")
    
    def _run_transcript_integration(
        self, 
        file_path: Path, 
        meeting_name: str, 
        meeting_type: str
    ):
        """Run transcript integration in a separate thread."""
        try:
            print("\nStarting AI analysis...")
            print("This may take a minute or two...\n")
            
            # Create a queue for results
            result_queue = queue.Queue()
            exception_queue = queue.Queue()
            
            def run_async():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    from .integrator import TranscriptIntegrator
                    
                    async def process():
                        integrator = TranscriptIntegrator()
                        await integrator.setup()
                        
                        result = await integrator.process_transcript(
                            transcript_path=str(file_path),
                            meeting_name=meeting_name,
                            meeting_type=meeting_type,
                        )
                        
                        await integrator.close()
                        return result
                    
                    result = loop.run_until_complete(process())
                    result_queue.put(result)
                    
                except Exception as e:
                    exception_queue.put(e)
                finally:
                    try:
                        loop.close()
                    except:
                        pass
            
            # Run in separate thread
            thread = threading.Thread(target=run_async)
            thread.start()
            thread.join(timeout=300)  # 5 minute timeout
            
            if thread.is_alive():
                print("ERROR: Analysis timed out after 5 minutes.")
                logger.error("Transcript integration timed out")
                return
            
            # Check for exceptions
            if not exception_queue.empty():
                exc = exception_queue.get()
                print(f"ERROR: Analysis failed: {exc}")
                logger.error(f"Transcript integration error: {exc}", exc_info=True)
                return
            
            # Get result
            if result_queue.empty():
                print("ERROR: No result from analysis.")
                return
            
            result = result_queue.get()
            
            # Display results
            print(f"\n{'='*50}")
            print("AI ANALYSIS COMPLETE")
            print(f"{'='*50}")
            print(f"Meeting ID: {result.get('meeting_id', 'N/A')}")
            print(f"\nMembers Identified: {result.get('members_identified', 0)}")
            if result.get('member_names'):
                for name in result['member_names']:
                    print(f"  - {name}")
            
            print(f"\nProjects Linked: {result.get('projects_linked', 0)}")
            if result.get('project_names'):
                for name in result['project_names']:
                    print(f"  - {name}")
            
            print(f"\nTopics: {result.get('topics_linked', 0)} linked, {result.get('new_topics_created', 0)} new")
            if result.get('topic_names'):
                for name in result['topic_names']:
                    print(f"  - {name}")
            
            print(f"\nTasks Created: {result.get('tasks_created', 0)}")
            if result.get('task_names'):
                for name in result['task_names']:
                    print(f"  - {name}")
            
            print(f"\nSummary: {result.get('summary_length', 0)} characters")
            print(f"{'='*50}")
            
        except Exception as e:
            print(f"ERROR: {e}")
            logger.error(f"Transcript integration error: {e}", exc_info=True)


class FileWatcher:
    """Main file watcher class that monitors the landing directory."""
    
    def __init__(self, watch_directory: str, integrator=None):
        """
        Initialize the file watcher.
        
        Args:
            watch_directory: Path to the landing directory to monitor
            integrator: Optional TranscriptIntegrator instance
        """
        self.watch_directory = Path(watch_directory)
        self.integrator = integrator
        self.observer = Observer()
        self.handler = FileWatcherHandler(self.watch_directory, integrator)
    
    def start(self) -> bool:
        """Start watching the directory."""
        if not self.watch_directory.exists():
            logger.error(f"Directory does not exist: {self.watch_directory}")
            print(f"ERROR: Directory does not exist: {self.watch_directory}")
            return False
        
        if not self.watch_directory.is_dir():
            logger.error(f"Path is not a directory: {self.watch_directory}")
            print(f"ERROR: Path is not a directory: {self.watch_directory}")
            return False
        
        # Schedule the watcher
        self.observer.schedule(
            self.handler,
            str(self.watch_directory),
            recursive=False  # Only watch the root, not subfolders
        )
        
        # Start observer
        self.observer.start()
        logger.info(f"Started watching: {self.watch_directory}")
        
        print(f"\n{'='*60}")
        print("FILE WATCHER ACTIVE")
        print(f"{'='*60}")
        print(f"Watching: {self.watch_directory}")
        print(f"\nDrop transcript files (.txt) into this folder to process them.")
        print(f"Press Ctrl+C to stop watching.\n")
        
        return True
    
    def stop(self):
        """Stop watching the directory."""
        self.observer.stop()
        self.observer.join()
        logger.info("File watcher stopped")
        print("\nFile watcher stopped.")
    
    def run(self):
        """Run the file watcher until interrupted."""
        if not self.start():
            return
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\nStopping file watcher...")
            self.stop()


def get_landing_directory() -> Path:
    """Get the path to the landing directory."""
    # Get the project root (parent of transcript_integrator)
    current_dir = Path(__file__).parent
    project_root = current_dir.parent
    landing_dir = project_root / "landing"
    return landing_dir


# CLI interface
def main():
    """Main function for CLI usage."""
    import sys
    
    print("=" * 60)
    print("Transcript File Watcher")
    print("=" * 60)
    
    # Determine landing directory
    if len(sys.argv) > 1:
        landing_dir = Path(sys.argv[1])
    else:
        landing_dir = get_landing_directory()
    
    print(f"\nLanding directory: {landing_dir}")
    
    if not landing_dir.exists():
        print(f"\nCreating landing directory...")
        landing_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subfolders
        for key, (folder, _) in MEETING_TYPES.items():
            (landing_dir / folder).mkdir(exist_ok=True)
        
        print("Created landing directory with subfolders.")
    
    # List subfolders
    print("\nSubfolders:")
    for item in sorted(landing_dir.iterdir()):
        if item.is_dir() and not item.name.startswith('.'):
            print(f"  - {item.name}/")
    
    # Start watching
    watcher = FileWatcher(str(landing_dir))
    watcher.run()


if __name__ == "__main__":
    main()
