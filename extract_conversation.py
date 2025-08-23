#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_conversation.py

Extract a single conversation/thread from a large ChatGPT-style JSON export and
write it out as a fully closed, valid JSON file (preserving the original structure
for the selected conversation).

Supported filters:
- --by-title "substring"        (case-insensitive substring match on conversation title)
- --by-id CONVERSATION_ID       (exact match on conversation_id)
- --by-snippet "text / regex"   (search any message content with substring or regex, case-insensitive)
- --after YYYY-MM-DD            (filter conversations that started on/after this date)
- --before YYYY-MM-DD           (filter conversations that started on/before this date)
- --index N                     (when multiple matches, pick the Nth (0-based) match)

Input formats handled (best-effort):
- A JSON object with a "conversations" array (OpenAI-style export)
- A JSON list of conversation objects
- JSON Lines (one JSON object per line) containing conversation objects

Examples:
    python extract_conversation.py export.json --by-title "beach birthday" -o beach_birthday.json
    python extract_conversation.py export.json --by-id abc123 -o convo_abc123.json
    python extract_conversation.py export.json --by-snippet "sacred vibrator" -o relic_scene.json
    python extract_conversation.py export.json --by-title "massage" --after 2025-08-01 -o massage_aug.json
    python extract_conversation.py export.json --by-title "beach" --index 0 -o first_beach.json

Notes:
- If multiple filters are provided, they are ANDed together.
- If multiple matches remain, use --index to choose which one to export.
- The output preserves the original conversation object JSON.
- If you want "human readable text" instead, this script is not for that—it's for valid JSON extraction.
"""

import json
import argparse
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

def load_export(path: str) -> List[Dict[str, Any]]:
    """
    Load conversations from various possible formats.
    Returns a list of conversation dicts.
    """
    # Try regular JSON first
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    text_stripped = text.lstrip()
    conversations: List[Dict[str, Any]] = []
    try:
        data = json.loads(text)
        # Common: {"conversations":[...]} or just [...]
        if isinstance(data, dict) and "conversations" in data and isinstance(data["conversations"], list):
            conversations = data["conversations"]
        elif isinstance(data, list):
            conversations = data
        else:
            # Maybe it's a dict where conversations are under another key
            for k, v in data.items() if isinstance(data, dict) else []:
                if isinstance(v, list) and v and isinstance(v[0], dict) and ("title" in v[0] or "mapping" in v[0] or "messages" in v[0]):
                    conversations = v
                    break
        if conversations:
            return conversations
    except Exception:
        pass

    # Try JSON Lines (one conversation per line)
    conversations = []
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                # Heuristic: likely a conversation object if it has any of these keys
                if isinstance(obj, dict) and any(k in obj for k in ("conversation_id", "title", "mapping", "messages")):
                    conversations.append(obj)
            except Exception:
                continue
        if conversations:
            return conversations
    except Exception:
        pass

    raise ValueError("Could not detect a supported export format. Expecting a list of conversations, "
                     "a {'conversations': [...]} object, or JSONL with one conversation per line.")

def conv_title(conv: Dict[str, Any]) -> str:
    return str(conv.get("title", ""))

def conv_id(conv: Dict[str, Any]) -> str:
    for key in ("conversation_id", "id", "uuid", "cid"):
        if key in conv:
            return str(conv[key])
    return ""

def conv_start_time(conv: Dict[str, Any]) -> Optional[datetime]:
    """
    Attempt to extract a representative 'start time' for the conversation.
    Heuristics: check typical fields, else earliest message timestamp.
    """
    # Common fields that might exist
    for key in ("create_time", "created_at", "start_time"):
        if key in conv:
            try:
                # could be epoch, iso, or string
                val = conv[key]
                if isinstance(val, (int, float)):
                    return datetime.fromtimestamp(val)
                if isinstance(val, str):
                    # Try ISO parse
                    try:
                        return datetime.fromisoformat(val.replace("Z", "+00:00"))
                    except Exception:
                        pass
            except Exception:
                pass

    # Look into messages for earliest timestamp
    msgs = None
    if "messages" in conv and isinstance(conv["messages"], list):
        msgs = conv["messages"]
    elif "mapping" in conv and isinstance(conv["mapping"], dict):
        # OpenAI-style "mapping" (nodes keyed by id)
        nodes = conv["mapping"].values()
        msgs = [n.get("message") for n in nodes if isinstance(n, dict) and isinstance(n.get("message"), dict)]

    earliest = None
    if msgs:
        for m in msgs:
            if not isinstance(m, dict):
                continue
            ts = None
            for key in ("create_time", "created_at", "timestamp"):
                if key in m:
                    ts = m[key]
                    break
            if ts is not None:
                try:
                    if isinstance(ts, (int, float)):
                        dt = datetime.fromtimestamp(ts)
                    elif isinstance(ts, str):
                        try:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except Exception:
                            continue
                    else:
                        continue
                    if earliest is None or dt < earliest:
                        earliest = dt
                except Exception:
                    continue
    return earliest

def conv_matches_filters(conv: Dict[str, Any],
                         title_sub: Optional[str],
                         cid: Optional[str],
                         snippet: Optional[str],
                         after: Optional[datetime],
                         before: Optional[datetime]) -> bool:
    # Title filter
    if title_sub:
        if title_sub.lower() not in conv_title(conv).lower():
            return False
    # ID filter
    if cid:
        if cid != conv_id(conv):
            return False
    # Date filters
    if after or before:
        st = conv_start_time(conv)
        if st is None:
            return False
        if after and st < after:
            return False
        if before and st > before:
            return False
    # Snippet filter: search messages text
    if snippet:
        patt = snippet
        try:
            rx = re.compile(patt, re.IGNORECASE)
        except re.error:
            rx = None
        # Search messages content
        def iter_messages(conv_obj: Dict[str, Any]):
            if "messages" in conv_obj and isinstance(conv_obj["messages"], list):
                for m in conv_obj["messages"]:
                    yield m
            elif "mapping" in conv_obj and isinstance(conv_obj["mapping"], dict):
                for node in conv_obj["mapping"].values():
                    msg = node.get("message")
                    if isinstance(msg, dict):
                        yield msg

        found = False
        for m in iter_messages(conv):
            # Try common content locations
            chunks = []
            if isinstance(m.get("content"), dict):
                # e.g., {"parts": ["..."]}
                if "parts" in m["content"] and isinstance(m["content"]["parts"], list):
                    chunks.extend([str(p) for p in m["content"]["parts"]])
                # other shapes possible
                for v in m["content"].values():
                    if isinstance(v, str):
                        chunks.append(v)
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                chunks.append(item)
            elif isinstance(m.get("content"), list):
                chunks.extend([str(x) for x in m["content"] if isinstance(x, str)])
            elif isinstance(m.get("content"), str):
                chunks.append(m["content"])
            # Sometimes text under "text"
            if "text" in m and isinstance(m["text"], str):
                chunks.append(m["text"])
            # Fallback: entire message as str
            if not chunks:
                chunks.append(json.dumps(m, ensure_ascii=False))

            for ch in chunks:
                if rx:
                    if rx.search(ch):
                        found = True
                        break
                else:
                    if patt.lower() in ch.lower():
                        found = True
                        break
            if found:
                break
        if not found:
            return False

    return True

def main():
    ap = argparse.ArgumentParser(description="Extract a single conversation from a ChatGPT-style JSON export.")
    ap.add_argument("input", help="Path to the JSON/JSONL export file")
    ap.add_argument("-o", "--output", required=True, help="Path to write the extracted conversation JSON")
    ap.add_argument("--by-title", dest="by_title", help="Case-insensitive substring of conversation title")
    ap.add_argument("--by-id", dest="by_id", help="Exact conversation_id to extract")
    ap.add_argument("--by-snippet", dest="by_snippet", help="Substring or regex to search within messages")
    ap.add_argument("--after", dest="after", help="Only conversations on/after YYYY-MM-DD")
    ap.add_argument("--before", dest="before", help="Only conversations on/before YYYY-MM-DD")
    ap.add_argument("--index", dest="index", type=int, default=0, help="Which match to choose if multiple (0-based)")

    args = ap.parse_args()

    # Parse date filters if any
    after_dt = datetime.fromisoformat(args.after) if args.after else None
    before_dt = datetime.fromisoformat(args.before) if args.before else None

    conversations = load_export(args.input)
    matches = []
    for i, conv in enumerate(conversations):
        if conv_matches_filters(conv, args.by_title, args.by_id, args.by_snippet, after_dt, before_dt):
            matches.append((i, conv))

    if not matches:
        sys.stderr.write("No conversations matched the given filters.\n")
        sys.exit(2)

    if args.index < 0 or args.index >= len(matches):
        sys.stderr.write(f"--index {args.index} is out of range for {len(matches)} matches.\n")
        for idx, (orig_index, conv) in enumerate(matches[:20]):
            cid = conv_id(conv) or "(no id)"
            title = conv_title(conv) or "(no title)"
            st = conv_start_time(conv)
            st_str = st.isoformat() if st else "(unknown time)"
            sys.stderr.write(f"  [{idx}] source_index={orig_index}, id={cid}, title={title}, start={st_str}\n")
        sys.exit(3)

    chosen_index, chosen_conv = matches[args.index]

    # Write out the chosen conversation as valid JSON
    with open(args.output, "w", encoding="utf-8") as out:
        json.dump(chosen_conv, out, ensure_ascii=False, indent=2)

    # Print a small summary to stderr for convenience
    cid = conv_id(chosen_conv) or "(no id)"
    title = conv_title(chosen_conv) or "(no title)"
    st = conv_start_time(chosen_conv)
    st_str = st.isoformat() if st else "(unknown time)"
    sys.stderr.write(f"Extracted conversation -> id={cid}, title={title}, start={st_str}\n")
    sys.stderr.write(f"Saved to {args.output}\n")

if __name__ == "__main__":
    main()
