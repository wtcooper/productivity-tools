"""Git facts for a project: worktrees, commits, reverts, merges, and unmerged work."""

import re
from pathlib import Path

from _common import git_out, parse_ts

AGENT_TRAILER = re.compile(r"co-authored-by:.*(claude|codex|copilot|cursor|anthropic|openai|gemini)", re.I)


def is_repo(root):
    return bool(git_out(root, "rev-parse", "--git-dir").strip())


def worktrees(root):
    out = git_out(root, "worktree", "list", "--porcelain")
    return [Path(line[9:]) for line in out.splitlines() if line.startswith("worktree ")]


def remote(root):
    url = git_out(root, "remote", "get-url", "origin").strip()
    return re.sub(r"^(https?://|git@)|\.git$", "", url).replace(":", "/", 1) if url else None


def default_branch(root):
    head = git_out(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
    if head:
        return head
    for name in ("main", "master", "trunk"):
        if git_out(root, "rev-parse", "--verify", "--quiet", name).strip():
            return name
    return git_out(root, "rev-parse", "--abbrev-ref", "HEAD").strip() or "HEAD"


def commits(root):
    """All commits on all refs, oldest first."""
    fmt = "%x1e%H%x1f%aI%x1f%an%x1f%P%x1f%s%x1f%b%x1f"
    raw = git_out(root, "log", "--all", "--reverse", "--date-order", f"--format={fmt}", "--numstat")
    on_default = set(git_out(root, "rev-list", default_branch(root)).split())
    result = []
    for record in raw.split("\x1e")[1:]:
        sha, date, author, parents, subject, body, numstat = record.split("\x1f")
        files, ins, dels = [], 0, 0
        for line in numstat.strip().splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                files.append(parts[2])
                ins += int(parts[0]) if parts[0].isdigit() else 0
                dels += int(parts[1]) if parts[1].isdigit() else 0
        result.append({
            "sha": sha,
            "sha7": sha[:7],
            "ts": parse_ts(date).isoformat(),
            "author": author,
            "subject": subject.strip(),
            "merge": len(parents.split()) > 1,
            "revert": subject.startswith('Revert "') or "This reverts commit" in body,
            "agent_trailer": bool(AGENT_TRAILER.search(body)),
            "merged": sha in on_default,
            "files": files,
            "insertions": ins,
            "deletions": dels,
            "session": None,
        })
    return result


def first_added(root, names):
    """ISO date a file was first committed (any of names), or None."""
    out = git_out(root, "log", "--all", "--diff-filter=A", "--reverse", "--format=%aI", "--", *names)
    first = out.strip().splitlines()[:1]
    return parse_ts(first[0]).date().isoformat() if first else None
