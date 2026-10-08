#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Gate for model-written output: structure, real evidence ids, matching quotes, no secrets.

    uv run scripts/check_evidence.py cards|story|coach [--project PATH]

cards  checks work/<project>/cards/*.json for the current digests
story  checks work/<project>/story.json
coach  checks work/<project>/coach.json
Exit 1 with one line per problem. Contracts: references/story-schema.md, ../dev-coach/references/rubric.md.
"""

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import load_work, read_json, read_ndjson, redact  # noqa: E402

OUTCOMES = {"shipped", "partial", "abandoned", "reverted", "exploration"}
BACKTRACKS = {"reverted", "re-planned", "abandoned", "thrashed", "scope-change"}
DIMENSIONS = ["framing", "planning", "context", "verification", "steering", "scope", "vcs", "delegation"]
FOLLOWED = {"mostly", "partly", "rarely", "n/a"}
QUOTE_KEYS = ("quote", "original_excerpt", "excerpt")


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


class Checker:
    def __init__(self, wd, manifest):
        texts = defaultdict(list)
        for e in read_ndjson(wd / "timeline.ndjson"):
            texts[e["id"]].append(e.get("text") or "")
        self.index = {k: "\n".join(v) for k, v in texts.items()}
        self.sessions = {s["short"] for s in manifest["sessions"]}
        self.commits = {c["sha7"] for c in manifest["commits"]}
        self.problems = []
        self.refs = 0

    def add(self, where, msg):
        self.problems.append(f"{where}: {msg}")

    def quote_ok(self, quote, ids):
        hay = norm(" ".join(self.index.get(i, "") for i in ids))
        frags = [norm(f) for f in re.split(r"…|\.\.\.", quote) if len(norm(f)) >= 8]
        return bool(frags) and all(f in hay for f in frags)

    def walk(self, obj, where, allowed_sessions=None):
        if isinstance(obj, dict):
            if "evidence" in obj:
                ids = [obj["evidence"]] if isinstance(obj["evidence"], str) else obj["evidence"] or []
                if not ids:
                    self.add(where, "claim has no evidence")
                for i in ids:
                    self.refs += 1
                    if i not in self.index:
                        self.add(where, f"unknown evidence id {i!r}")
                    elif allowed_sessions and not i.startswith("c:") and i.split(":")[0] not in allowed_sessions:
                        self.add(where, f"evidence {i!r} is from another session")
                for key in QUOTE_KEYS:
                    if obj.get(key) and ids and not self.quote_ok(obj[key], ids):
                        self.add(where, f"{key} not found verbatim in its evidence: {obj[key][:80]!r}")
            for k, v in obj.items():
                self.walk(v, f"{where}.{k}", allowed_sessions)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                self.walk(v, f"{where}[{i}]", allowed_sessions)
        elif isinstance(obj, str) and redact(obj) != obj:
            self.add(where, "contains what looks like a secret; remove it")

    def need(self, obj, where, keys):
        for k in keys:
            if not obj.get(k):
                self.add(where, f"missing {k!r}")

    def items(self, doc, key, where, required=True):
        val = doc.get(key)
        if not isinstance(val, list) or (required and not val):
            self.add(where, f"{key!r} must be a {'non-empty ' if required else ''}list")
            return []
        return val

    # ------------------------------------------------------------ documents

    def card(self, card, where, session):
        self.need(card, where, ["digest", "digest_sha", "session", "summary", "outcome", "goal"])
        if card.get("outcome") not in OUTCOMES | {"unknown"}:
            self.add(where, f"outcome must be one of {sorted(OUTCOMES | {'unknown'})}")
        if isinstance(card.get("goal"), dict):
            self.need(card["goal"], f"{where}.goal", ["text", "evidence"])
        for b in card.get("backtracks") or []:
            if b.get("type") not in BACKTRACKS:
                self.add(f"{where}.backtracks", f"type must be one of {sorted(BACKTRACKS)}")
        for key in ("decisions", "built", "backtracks", "open_threads"):
            for i, item in enumerate(card.get(key) or []):
                if "evidence" not in item:
                    self.add(f"{where}.{key}[{i}]", "claim has no evidence")
        self.walk(card, where, {session})

    def story(self, doc):
        w = "story.json"
        self.need(doc, w, ["headline", "origin", "chapters", "episodes"])
        self.need(doc.get("origin") or {}, f"{w}.origin", ["problem_statement", "intent", "evidence"])
        episodes = {e.get("id"): e for e in self.items(doc, "episodes", w)}
        placed = defaultdict(int)
        for i, ch in enumerate(self.items(doc, "chapters", w)):
            where = f"{w}.chapters[{i}]"
            self.need(ch, where, ["id", "title", "summary", "episodes", "evidence"])
            for ep in ch.get("episodes") or []:
                placed[ep] += 1
                if ep not in episodes:
                    self.add(where, f"unknown episode {ep!r}")
        for ep_id, ep in episodes.items():
            where = f"{w}.episodes[{ep_id}]"
            self.need(ep, where, ["id", "title", "outcome", "evidence"])
            if ep.get("outcome") not in OUTCOMES:
                self.add(where, f"outcome must be one of {sorted(OUTCOMES)}")
            if placed[ep_id] != 1:
                self.add(where, f"must appear in exactly one chapter (found {placed[ep_id]})")
            for s in ep.get("sessions") or []:
                if s not in self.sessions:
                    self.add(where, f"unknown session {s!r}")
            for c in ep.get("commits") or []:
                if c not in self.commits:
                    self.add(where, f"unknown commit {c!r}")
        for i, p in enumerate(self.items(doc, "pivots", w, required=False)):
            where = f"{w}.pivots[{i}]"
            self.need(p, where, ["type", "from", "to", "why", "evidence"])
            if p.get("type") not in BACKTRACKS:
                self.add(where, f"type must be one of {sorted(BACKTRACKS)}")
        for key in ("shipped", "open_threads", "lessons"):
            for i, item in enumerate(self.items(doc, key, w, required=False)):
                self.need(item, f"{w}.{key}[{i}]", ["what" if key == "shipped" else "text", "evidence"])
        for i, s in enumerate((doc.get("intent_drift") or {}).get("shifts") or []):
            self.need(s, f"{w}.intent_drift.shifts[{i}]", ["what", "evidence"])
        self.walk(doc, w)

    def coach(self, doc):
        w = "coach.json"
        dims = {d.get("id"): d for d in self.items(doc, "dimensions", w)}
        if sorted(dims) != sorted(DIMENSIONS):
            self.add(w, f"dimensions must be exactly {DIMENSIONS}")
        for dim_id, d in dims.items():
            where = f"{w}.dimensions[{dim_id}]"
            self.need(d, where, ["summary"])
            if d.get("score") is None:
                if not d.get("insufficient_evidence"):
                    self.add(where, "score is null without insufficient_evidence: true")
                continue
            if d.get("score") not in (1, 2, 3, 4):
                self.add(where, "score must be 1-4")
            cited = {i for item in (d.get("strengths") or []) + (d.get("gaps") or []) for i in item.get("evidence") or []}
            if len(cited) < 2:
                self.add(where, "a scored dimension needs at least 2 distinct evidence ids")
        habits = self.items(doc, "habits", w)
        if len(habits) != 3:
            self.add(w, "habits must have exactly 3 items")
        for i, h in enumerate(habits):
            self.need(h, f"{w}.habits[{i}]", ["title", "detail", "dimension"])
            if h.get("dimension") not in DIMENSIONS:
                self.add(f"{w}.habits[{i}]", "dimension must be a rubric id")
        for i, r in enumerate(self.items(doc, "rewrites", w)):
            self.need(r, f"{w}.rewrites[{i}]", ["evidence", "original_excerpt", "rewrite", "why"])
        for i, b in enumerate(self.items(doc, "best_prompts", w, required=False)):
            self.need(b, f"{w}.best_prompts[{i}]", ["evidence", "excerpt", "why"])
        for i, r in enumerate(self.items(doc, "own_rules", w, required=False)):
            self.need(r, f"{w}.own_rules[{i}]", ["rule", "followed"])
            if r.get("followed") not in FOLLOWED:
                self.add(f"{w}.own_rules[{i}]", f"followed must be one of {sorted(FOLLOWED)}")
        self.walk(doc, w)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", choices=["cards", "story", "coach"])
    ap.add_argument("--project", default=".")
    args = ap.parse_args()
    root, wd, manifest = load_work(args.project)
    ck = Checker(wd, manifest)

    if args.target == "cards":
        pending = []
        for s in manifest["sessions"]:
            for name in s.get("digests", []):
                card = read_json(wd / "cards" / f"{name}.json")
                sha = hashlib.sha256((wd / "digests" / f"{name}.md").read_bytes()).hexdigest()[:16]
                if card is None or card.get("digest_sha") != sha:
                    pending.append(name)
                else:
                    ck.card(card, f"cards/{name}.json", s["short"])
        if pending:
            ck.add("cards", f"{len(pending)} digests have no up-to-date card: {', '.join(pending[:10])}")
    else:
        doc = read_json(wd / f"{args.target}.json")
        if doc is None:
            sys.exit(f"error: {wd / (args.target + '.json')} does not exist")
        getattr(ck, args.target)(doc)

    if ck.problems:
        print(f"FAIL: {len(ck.problems)} problem(s)")
        print("\n".join(ck.problems[:200]))
        sys.exit(1)
    print(f"OK: {args.target} — {ck.refs} evidence references checked")


if __name__ == "__main__":
    main()
