#!/usr/bin/env python3

import sys
import subprocess
import re
import os
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from pathlib import Path
from git import Repo, GitCommandError
from colorama import init, Fore, Style
import tempfile
from enum import Enum

# Initialize colorama
init(autoreset=True)

class ViewMode(Enum):
    HUNK = "hunk"
    FILE = "file"

@dataclass
class ConflictHunk:
    """Represents a single conflict hunk in a file."""
    header: str
    ours: List[str]
    theirs: List[str]
    context_before: List[str]  # Added context lines
    context_after: List[str]   # Added context lines
    start_line: Optional[int] = None

class GitConflictResolver:
    """Handles Git conflict resolution operations."""
    
    def __init__(self):
        self.editor = os.environ.get('EDITOR', 'nano')
        self.view_mode = ViewMode.FILE  # Default to file view
        self.context_lines = 3  # Number of context lines to show
        try:
            self.repo = Repo(Path.cwd())
        except Exception as e:
            print(Fore.RED + f"Error initializing Git repository: {e}")
            sys.exit(1)

    def get_conflicted_files(self) -> List[str]:
        """Retrieve a list of conflicted files in the repository."""
        try:
            conflicted = [item.a_path for item in self.repo.index.unmerged_blobs().values()]
            return list(set(conflicted))
        except GitCommandError as e:
            print(Fore.RED + f"Error getting conflicted files: {e}")
            return []

    def get_file_content(self, file_path: str) -> List[str]:
        """Get file content with line numbers."""
        try:
            with open(file_path, 'r') as f:
                return f.readlines()
        except IOError as e:
            print(Fore.RED + f"Error reading file {file_path}: {e}")
            return []

    def extract_context(self, content: List[str], start: int, end: int) -> Tuple[List[str], List[str]]:
        """Extract context lines before and after a hunk."""
        before = content[max(0, start - self.context_lines):start]
        after = content[end:min(len(content), end + self.context_lines)]
        return before, after

    def get_conflicts(self, file_path: str) -> List[ConflictHunk]:
        """Extract conflict hunks with context for a given file."""
        content = self.get_file_content(file_path)
        hunks = []
        current_hunk = None
        state = None
        hunk_start = None

        for i, line in enumerate(content):
            if line.startswith('<<<<<<<'):
                if current_hunk:
                    # Add context to previous hunk
                    before, after = self.extract_context(content, hunk_start, i)
                    current_hunk.context_before = before
                    current_hunk.context_after = after
                    hunks.append(current_hunk)

                hunk_start = i
                current_hunk = ConflictHunk(header=line, ours=[], theirs=[], 
                                          context_before=[], context_after=[],
                                          start_line=i)
                state = 'ours'
            elif line.startswith('=======') and state == 'ours':
                state = 'theirs'
            elif line.startswith('>>>>>>>') and state == 'theirs':
                if current_hunk:
                    current_hunk.theirs.append(line)
                    # Add context for the last hunk
                    before, after = self.extract_context(content, hunk_start, i + 1)
                    current_hunk.context_before = before
                    current_hunk.context_after = after
                    hunks.append(current_hunk)
                current_hunk = None
                state = None
            elif current_hunk and state:
                if state == 'ours':
                    current_hunk.ours.append(line)
                else:
                    current_hunk.theirs.append(line)

        return hunks

    def launch_vimdiff(self, file_path: str):
        """Launch vimdiff for the conflicted file."""
        try:
            subprocess.run(['vimdiff', 
                          f'{file_path}.LOCAL',
                          f'{file_path}.BASE', 
                          f'{file_path}.REMOTE'])
            return True
        except subprocess.SubprocessError as e:
            print(Fore.RED + f"Error launching vimdiff: {e}")
            return False

    def display_file_view(self, file_path: str, hunks: List[ConflictHunk]):
        """Display the entire file with conflicts highlighted."""
        content = self.get_file_content(file_path)
        in_conflict = False
        
        print(f"\n{Fore.BLUE}File: {file_path}")
        print(f"{Fore.BLUE}{'='*80}")
        
        for i, line in enumerate(content, 1):
            if line.startswith('<<<<<<<'):
                in_conflict = True
                print(f"{Fore.RED}{i:4d}│ {line}", end='')
            elif line.startswith('=======') and in_conflict:
                print(f"{Fore.YELLOW}{i:4d}│ {line}", end='')
            elif line.startswith('>>>>>>>') and in_conflict:
                in_conflict = False
                print(f"{Fore.GREEN}{i:4d}│ {line}", end='')
            elif in_conflict:
                color = Fore.RED if in_conflict else Fore.GREEN
                print(f"{color}{i:4d}│ {line}", end='')
            else:
                print(f"{Style.RESET_ALL}{i:4d}│ {line}", end='')

    def display_hunk(self, hunk: ConflictHunk, hunk_index: int):
        """Display a single hunk with context."""
        print(f"\n{Fore.BLUE}Conflict {hunk_index + 1}:")
        print(f"{Fore.BLUE}{'='*80}")
        
        # Display context before
        for line in hunk.context_before:
            print(Style.RESET_ALL + line.rstrip())
        
        # Display conflict
        print(Fore.RED + hunk.header)
        print(Fore.RED + '<<<<<<< ours')
        for line in hunk.ours:
            print(Fore.RED + line.rstrip())
        print(Fore.YELLOW + '=======')
        for line in hunk.theirs:
            print(Fore.GREEN + line.rstrip())
        print(Fore.GREEN + '>>>>>>> theirs')
        
        # Display context after
        for line in hunk.context_after:
            print(Style.RESET_ALL + line.rstrip())

    def prompt_user(self) -> str:
        """Prompt the user for action with expanded options."""
        options = {
            'o': "Keep 'ours'",
            't': "Keep 'theirs'",
            'e': "Edit manually",
            'v': "Open in vimdiff",
            'm': f"Toggle view mode (current: {self.view_mode.value})",
            'c': "Show more context",
            's': "Skip this hunk",
            'q': "Quit"
        }
        
        print("\nOptions:")
        for key, value in options.items():
            print(f"{Fore.CYAN}{key}{Style.RESET_ALL}) {value}")
        
        while True:
            choice = input("Choose an option [o/t/e/v/m/c/s/q]: ").strip().lower()
            if choice in options:
                return choice
            print(Fore.RED + "Invalid option. Please try again.")

    def process_file(self, file_path: str):
        """Process conflicts in a file with support for different view modes."""
        hunks = self.get_conflicts(file_path)
        
        if not hunks:
            print(Fore.YELLOW + "No conflict hunks found in this file.")
            return

        while True:
            if self.view_mode == ViewMode.FILE:
                self.display_file_view(file_path, hunks)
            else:
                for idx, hunk in enumerate(hunks):
                    self.display_hunk(hunk, idx)

            choice = self.prompt_user()
            
            if choice == 'q':
                print(Fore.MAGENTA + "Quitting script.")
                sys.exit(0)
            elif choice == 'm':
                self.view_mode = ViewMode.HUNK if self.view_mode == ViewMode.FILE else ViewMode.FILE
                print(Fore.CYAN + f"Switched to {self.view_mode.value} view.")
            elif choice == 'c':
                self.context_lines = min(self.context_lines + 3, 10)
                print(Fore.CYAN + f"Showing {self.context_lines} lines of context.")
            elif choice == 'v':
                self.launch_vimdiff(file_path)
            elif choice == 'e':
                subprocess.run([self.editor, file_path])
                try:
                    self.repo.index.add([file_path])
                    print(Fore.CYAN + "Manually edited and staged the file.")
                    break
                except GitCommandError as e:
                    print(Fore.RED + f"Error staging file: {e}")
            else:
                # Handle regular conflict resolution
                self.resolve_hunk(file_path, hunks[0], 0)  # Start with first hunk
                break

def main():
    # Check if running as mergetool
    if len(sys.argv) > 1 and sys.argv[1] == '--mergetool':
        local = os.environ.get('LOCAL')
        base = os.environ.get('BASE')
        remote = os.environ.get('REMOTE')
        merged = os.environ.get('MERGED')
        
        if all([local, base, remote, merged]):
            resolver = GitConflictResolver()
            resolver.process_file(merged)
            sys.exit(0)

    # Regular operation
    resolver = GitConflictResolver()
    conflicted_files = resolver.get_conflicted_files()

    if not conflicted_files:
        print(Fore.GREEN + "No conflicted files found. Exiting.")
        sys.exit(0)

    for file_path in conflicted_files:
        resolver.process_file(file_path)

    print(Fore.GREEN + "\nAll conflicts processed.")

if __name__ == "__main__":
    main()
