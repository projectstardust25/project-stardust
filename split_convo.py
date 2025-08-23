#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
split_convo_configaware.py
Split a single conversation JSON into themed slices using [[SPLIT]] markers.

Markers in any message "content":
  [[SPLIT HERE]]               → split and drop marker message
  [[SPLIT: name]]              → split and name the next slice

Config:
  Reads stardust_config.yaml from (in order):
    ./stardust_config.yaml
    ~/.stardust/config.yaml
    ./Project_Stardust/config.yaml

CLI flags override config.
"""
import json, re, hashlib, argparse
from pathlib import Path
from datetime import datetime

# ---------- Config loading ----------
def load_config():
    paths = [
        Path.cwd() / "stardust_config.yaml",
        Path.home() / ".stardust" / "config.yaml",
        Path.cwd() / "Project_Stardust" / "config.yaml",
    ]
    cfg = {}
    for p in paths:
        if p.exists():
            try:
                import yaml  # requires PyYAML
                with p.open("r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                break
            except Exception:
                try:
                    cfg = json.loads(p.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass
    out = cfg.get("output", {}) if isinstance(cfg, dict) else {}
    defaults = cfg.get("defaults", {}) if isinstance(cfg, dict) else {}
    return {
        "filename_template": out.get("filename_template", "convo_{date}_{time}_{id}_{slice}_{slug}.json"),
        "slug_maxlen": int(out.get("slug_maxlen", 50)),
        "include_sha256": bool(out.get("include_sha256", True)),
        "default_slice_name": defaults.get("slice_name", "slice"),
        "default_tags": defaults.get("tags", []),
    }

SPLIT_RE = re.compile(r"\[\[\s*SPLIT(?:\s*:\s*([^\]]+))?\s*\]\]", re.IGNORECASE)

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def slugify(text: str, max_len: int = 60) -> str:
    import re
    text = re.sub(r"\s+", "-", (text or "").strip())
    text = re.sub(r"[^a-zA-Z0-9\-_]+", "", text)
    return (text[:max_len].strip("-_") or "slice")

def parse_args(config):
    p = argparse.ArgumentParser(description="Split a conversation JSON into themed slices using [[SPLIT]] markers.")
    p.add_argument("--input", "-i", required=True, help="Path to single-conversation JSON")
    p.add_argument("--outdir", "-o", required=True, help="Output directory for slices")
    p.add_argument("--filename-template", default=config["filename_template"],
                   help="Template tokens: {date} {time} {id} {slice} {slug} {n}")
    p.add_argument("--default-slice-name", default=config["default_slice_name"], help="Base name for unnamed slices")
    p.add_argument("--tag", action="append", default=None, help="Tag(s) to add to each slice manifest (repeatable)")
    p.add_argument("--auto-title", action="store_true", help="Derive human title from first non-empty user line")
    p.add_argument("--slug-maxlen", type=int, default=config["slug_maxlen"], help="Max length for slugified title")
    p.add_argument("--dry-run", action="store_true", help="Don’t write files; print plan only")
    return p.parse_args()

def normalize_convo(raw):
    convo = {}
    convo["id"] = raw.get("id") or raw.get("conversation_id") or "unknown_id"
    convo["title"] = raw.get("title") or "Untitled Conversation"
    created = raw.get("create_time") or raw.get("created_at") or raw.get("created") or raw.get("start_time")
    dt = None
    if isinstance(created, (int, float)):
        dt = datetime.fromtimestamp(created)
    elif isinstance(created, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ","%Y-%m-%dT%H:%M:%S%z","%Y-%m-%dT%H:%M:%S","%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(created, fmt); break
            except Exception:
                pass
    if dt is None:
        dt = datetime.now()
    convo["date"] = dt.strftime("%Y-%m-%d")
    convo["time"] = dt.strftime("%H-%M-%S")
    messages = raw.get("messages")
    if isinstance(messages, list):
        pass
    elif isinstance(raw.get("mapping"), dict):
        mapping = raw["mapping"]
        messages = []
        for _mid, node in mapping.items():
            msg = node.get("message") or {}
            if not msg: 
                continue
            if isinstance(msg.get("content"), dict):
                parts = msg["content"].get("parts") or []
                content = "\n".join(p for p in parts if isinstance(p, str))
            else:
                content = msg.get("content") if isinstance(msg.get("content"), str) else ""
            messages.append({
                "role": msg.get("author",{}).get("role","user"),
                "content": content or "",
                "create_time": msg.get("create_time")
            })
        messages.sort(key=lambda m: m.get("create_time") or 0)
    else:
        raise ValueError("Could not locate messages array. Expected 'messages' (list) or 'mapping' (dict).")
    convo["messages"] = messages
    return convo

def find_splits(messages):
    splits = []
    for idx, m in enumerate(messages):
        content = m.get("content") or ""
        mo = SPLIT_RE.search(content)
        if mo:
            name = (mo.group(1) or "").strip()
            splits.append((idx, name))
    return splits

def slice_messages(messages, splits, default_name="slice"):
    if not splits:
        return [("whole", 0, len(messages))]
    ranges = []
    prev = 0
    for sidx, name in splits:
        if sidx > prev:
            ranges.append(((name or default_name), prev, sidx))
        prev = sidx + 1  # drop marker message
    if prev < len(messages):
        ranges.append((default_name, prev, len(messages)))
    counts = {}
    named = []
    for base, a, b in ranges:
        counts[base] = counts.get(base, 0) + 1
        suffix = "" if counts[base] == 1 else f"-{counts[base]}"
        named.append((f"{base}{suffix}", a, b))
    return named

def derive_title(slice_msgs):
    for m in slice_msgs:
        if (m.get("role") == "user") and (m.get("content") or "").strip():
            return (m["content"].strip().split("\n")[0])[:80]
    for m in slice_msgs:
        if (m.get("role") == "assistant") and (m.get("content") or "").strip():
            return (m["content"].strip().split("\n")[0])[:80]
    return "Slice"

def main():
    config = load_config()
    args = parse_args(config)
    in_path = Path(args.input); outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    raw = json.loads(in_path.read_text(encoding="utf-8"))
    convo = normalize_convo(raw)
    splits = find_splits(convo["messages"])
    slices = slice_messages(convo["messages"], splits, default_name=args.default_slice_name)
    tags = args.tag if args.tag is not None else list(config["default_tags"])

    manifest = {
        "source_file": in_path.name,
        "conversation_id": convo["id"],
        "conversation_title": convo["title"],
        "date": convo["date"],
        "time": convo["time"],
        "slices": []
    }
    for n, (slice_name, a, b) in enumerate(slices, start=1):
        slice_msgs = convo["messages"][a:b]
        human_title = derive_title(slice_msgs) if args.auto_title else None
        slug = slugify(human_title or slice_name, max_len=args.slug_maxlen)
        fname = args.filename_template.format(
            date=convo["date"], time=convo["time"], id=convo["id"], slice=slice_name, slug=slug, n=n
        )
        out_file = outdir / fname
        slice_obj = {
            "id": convo["id"],
            "title": convo["title"],
            "date": convo["date"],
            "time": convo["time"],
            "slice": slice_name,
            "sequence": n,
            "tags": tags,
            "human_title": human_title,
            "messages": slice_msgs
        }
        data = json.dumps(slice_obj, ensure_ascii=False, indent=2).encode("utf-8")
        checksum = sha256_bytes(data)
        entry = {
            "file": fname,
            "slice": slice_name,
            "sequence": n,
            "human_title": human_title,
            "approx_message_range": [a, b]
        }
        if config["include_sha256"]:
            entry["sha256"] = checksum
        manifest["slices"].append(entry)
        if not args.dry_run:
            out_file.write_bytes(data)
    if not args.dry_run:
        (outdir / "index.json").write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    print(f"Slices: {len(slices)}")
    print(f"Output dir: {outdir}")
    for s in manifest["slices"]:
        line = f" - {s['file']}"
        if "sha256" in s:
            line += f"  [{s['sha256'][:8]}…]"
        print(line)

if __name__ == "__main__":
    main()