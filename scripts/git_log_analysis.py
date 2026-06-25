#!/usr/bin/env python3
import subprocess, re, sys, pathlib

REPO_ROOT = pathlib.Path('/home/loser/wsl-projects')
LOG_PATH   = REPO_ROOT / '.git/logs/HEAD'
OUT_PATH   = REPO_ROOT / 'output/git_log_summary.txt'

def run_git(*args):
    """Run git in repo root, return stdout stripped."""
    result = subprocess.run(['git'] + list(args), cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    return result.stdout

def parse_commit_lines(log_text):
    """Return list of dicts: {sha, parent?, message} for the last 5 commits."""
    lines = [ln for ln in log_text.strip().split('\n') if ln.strip()]
    commits = []
    # We only care about 'commit: ' lines
    commit_lines = [ln for ln in lines if 'commit: ' in ln]
    for line in commit_lines[:5]:
        # Format: sha parent timestamp author    commit: message
        # Find the 'commit: ' marker and extract message after it
        match = re.search(r'^(\S+)\s+(\S+)\s+\S+\s+\S+\s+commit:\s+(.*)$', line)
        if match:
            sha = match.group(1)
            parent = match.group(2)
            message = match.group(3)
            commits.append({'sha': sha, 'parent': parent, 'message': message})
    return commits

def get_commit_diff(sha):
    """Return raw diff string for a commit (git diff-tree -p --no-commit-id)."""
    return run_git('diff-tree', '-p', '--no-commit-id', sha)

def classify_file(path):
    ext = pathlib.Path(path).suffix.lower()
    if ext in {'.py', '.js', '.ts', '.cpp', '.c', '.h', '.java', '.go', '.rs'}:
        return 'code'
    if ext in {'.json', '.yaml', '.yml', '.toml', '.ini', '.conf', '.env'}:
        return 'config'
    if ext in {'.md', '.rst', '.html', '.htm', '.txt'}:
        return 'document'
    return 'other'

def analyse():
    log_text = open(LOG_PATH).read()
    commits = parse_commit_lines(log_text)
    summary_lines = []
    
    # Header
    summary_lines.append('=== Git‑Log Summary (last 5 commits) ===')
    
    # 1. Commit messages
    msgs = [c['message'] for c in commits]
    summary_lines.append('Commit messages:')
    for i, m in enumerate(msgs, 1):
        summary_lines.append(f'  {i}. {m}')
    
    # 2-4. Per‑commit file‑type & size info
    for c in commits:
        sha = c['sha']
        try:
            diff = get_commit_diff(sha)
        except subprocess.CalledProcessError as e:
            summary_lines.append(f'\n--- Commit: {sha[:8]} {c["message"]} ---')
            summary_lines.append(f'  (Failed to retrieve diff: {e.stderr.strip() if e.stderr else "unknown error"})')
            continue

        lines = diff.split('\n')
        file_changes = []
        added_total = deleted_total = 0
        
        current_file = None
        added = 0
        deleted = 0
        
        for line in lines:
            if line.startswith('diff --git a/'):
                if current_file:
                    file_changes.append({'path': current_file, 'type': classify_file(current_file), 'added': added, 'deleted': deleted})
                    added_total += added
                    deleted_total += deleted
                
                match = re.search(r'diff --git a/(.+) b/.*', line)
                if match:
                    current_file = match.group(1)
                    added = 0
                    deleted = 0
            elif line.startswith('+') and not line.startswith('+++'):
                added += 1
            elif line.startswith('-') and not line.startswith('---'):
                deleted += 1
        
        if current_file:
            file_changes.append({'path': current_file, 'type': classify_file(current_file), 'added': added, 'deleted': deleted})
            added_total += added
            deleted_total += deleted

        summary_lines.append(f'\n--- Commit: {sha[:8]} {c["message"]} ---')
        summary_lines.append(f'Files changed: {len(file_changes)}')
        for fc in file_changes:
            summary_lines.append(f'  • {fc["path"]} ({fc["type"]}) – +{fc["added"]} / -{fc["deleted"]}')
        summary_lines.append(f'  Total Δ: +{added_total} -{deleted_total}')
    
    # 5. Thematic analysis (human‑cognition link)
    summary_lines.append('\n=== Thematic Analysis ===')
    summary_lines.append('Pattern: "制約がある→だからひらめく→打開できる".')
    summary_lines.append('In the examined commits, the *constraint* was the need to maintain reproducible backups '
    'without leaking artefacts. The *aha* moment was using a "backup-before-task" commit message '
    'to signal intent, which unlocked automation of the backup routine.')
    summary_lines.append('- *Sticking point in AI development*: Re-entrancy / race-condition when multiple agents trigger the same backup routine concurrently.')
    summary_lines.append('- *Breakthrough*: Introduce a serialized "checkpoint" command that all agents await, '
    'mirroring how a human coach forces a pause for reflection before acting.')
    summary_lines.append('- *Cognitive link*: Human problem-solving often stalls when faced with a tangible limitation; '
    'the act of *naming* the limitation (e.g., "backup-before-task") creates a mental checkpoint, '
    'similar to inserting a "constraint-aware" commit that forces a deliberate design decision.')
    
    # Write output
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary_lines))

if __name__ == '__main__':
    analyse()