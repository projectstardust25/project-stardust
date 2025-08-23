#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
slice_by_ranges.py
Slice a conversation JSON into multiple files using explicit ranges or split boundaries.

Ranges by index:
  --range 0:36:morning_cuddle

Ranges by message id (from export tree):
  --range id:abc:id:def:project_stardust

Split-at boundaries (auto-build ranges):
  --split-at 36 83
  --slice-names morning_cuddle intimacy_breakfast project_stardust

Config:
  Reads stardust_config.yaml from (in order):
    ./stardust_config.yaml
    ~/.stardust/config.yaml
    ./Project_Stardust/config.yaml

CLI flags override config values.
"""
import json, argparse, hashlib, re
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
                import yaml
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
        "filename_template": out.get("filename_template", "convo_{date}_{time}_{id}_{slice}_{n}.json"),
        "slug_maxlen": int(out.get("slug_maxlen", 50)),
        "include_sha256": bool(out.get("include_sha256", True)),
        "default_slice_name": defaults.get("slice_name", "slice"),
        "default_tags": defaults.get("tags", []),
    }

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def slugify(text: str, max_len: int = 60) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^A-Za-z0-9\-_]+", "", text)
    text = text.strip("-_")
    return (text[:max_len] or "slice")

def parse_args(config):
    p = argparse.ArgumentParser(description="Slice a conversation JSON by index or message IDs.")
    p.add_argument("-i","--input", required=True, help="Path to single-conversation JSON")
    p.add_argument("-o","--outdir", required=True, help="Output directory")
    p.add_argument("--filename-template", default=config["filename_template"],
                   help="Tokens: {date} {time} {id} {slice} {n}")
    p.add_argument("--range", action="append", default=[],
                   help="Format: start:end:name where start/end are INT index or id:<msgid>. Repeatable.")
    p.add_argument("--split-at", nargs="*", default=[],
                   help="Boundary list (indexes or id:<msgid>) to cut sequential slices.")
    p.add_argument("--slice-names", nargs="*", default=[],
                   help="Optional names for sequential slices when using --split-at.")
    p.add_argument("--tag", action="append", default=None,
                   help="Tag(s) to include in each slice’s metadata. Repeatable.")
    p.add_argument("--auto-title", action="store_true",
                   help="Derive a quick human_title from first non-empty user line in the slice.")
    p.add_argument("--dry-run", action="store_true", help="Don’t write files, just print plan.")
    return p.parse_args()

def load_convo(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    cid = raw.get("id") or raw.get("conversation_id") or "unknown_id"
    title = raw.get("title") or "Untitled Conversation"
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
    date_s = dt.strftime("%Y-%m-%d"); time_s = dt.strftime("%H-%M-%S")

    messages = None
    if isinstance(raw.get("messages"), list):
        messages = []
        for m in raw["messages"]:
            mid = m.get("id") or m.get("message_id") or m.get("uuid")
            messages.append({**m, "_index": len(messages), "_orig_id": mid})
    elif isinstance(raw.get("mapping"), dict):
        mapping = raw["mapping"]
        nodes = []
        for node_id, node in mapping.items():
            msg = node.get("message")
            if not msg: 
                continue
            content = msg.get("content")
            if isinstance(content, dict):
                parts = content.get("parts") or []
                content_text = "\n".join(p for p in parts if isinstance(p, str))
            else:
                content_text = content if isinstance(content, str) else ""
            rec = {
                "role": msg.get("author",{}).get("role","user"),
                "content": content_text or "",
                "create_time": msg.get("create_time"),
                "id": msg.get("id") or None,
                "_node_id": node_id
            }
            nodes.append(rec)
        nodes.sort(key=lambda m: m.get("create_time") or 0)
        messages = []
        for m in nodes:
            messages.append({**m, "_index": len(messages), "_orig_id": m.get("id") or m.get("_node_id")})
    else:
        raise ValueError("Expected 'messages' (list) or 'mapping' (dict) in the input JSON.")

    return {"id": cid, "title": title, "date": date_s, "time": time_s, "messages": messages}

def index_for_token(messages, token):
    if isinstance(token, int):
        return token
    s = str(token)
    if s.startswith("id:"):
        needle = s[3:]
        for m in messages:
            if str(m.get("_orig_id") or "") == needle:
                return m["_index"]
        raise ValueError(f"Message ID not found: {needle}")
    try:
        return int(s)
    except Exception:
        raise ValueError(f"Bad boundary token: {token}")

def parse_range(rng, messages):
    """
    'start:end:name'
    start/end can be INT index or 'id:<id>'.
    We accept inputs like: '0:36:name' or 'id:abc:id:def:name'.
    If message IDs themselves contain colons (unlikely for ChatGPT exports), this parser would need to be extended.
    Returns (start_index, end_index_exclusive, name).
    """
    parts = rng.split(":")
    if not parts or len(parts) < 2:
        raise ValueError(f"--range must be start:end[:name], got {rng}")
    i = 0
    # Parse start token
    if parts[i] == "id":
        if i+1 >= len(parts):
            raise ValueError(f"Malformed start token in --range: {rng}")
        start_tok = f"id:{parts[i+1]}"
        i += 2
    else:
        start_tok = parts[i]
        i += 1
    # Parse end token
    if i >= len(parts):
        raise ValueError(f"Missing end token in --range: {rng}")
    if parts[i] == "id":
        if i+1 >= len(parts):
            raise ValueError(f"Malformed end token in --range: {rng}")
        end_tok = f"id:{parts[i+1]}"
        i += 2
    else:
        end_tok = parts[i]
        i += 1
    # The rest (if any) compose the name, joined by ':' to preserve user intent
    name = ":".join(parts[i:]) if i < len(parts) else "slice"
    a = index_for_token(messages, start_tok)
    b = index_for_token(messages, end_tok)
    if b < a:
        a, b = b, a
    return a, b+1, name

def build_ranges_from_split_at(split_tokens, messages, default_name="slice", slice_names=None):
    if not split_tokens:
        return [(0, len(messages), slice_names[0] if slice_names else default_name)]
    idxs = [index_for_token(messages, t) for t in split_tokens]
    idxs = sorted(set(i for i in idxs if 0 <= i < len(messages)))
    ranges = []
    prev = 0
    for i, cut in enumerate(idxs):
        if cut > prev:
            nm = slice_names[i] if slice_names and i < len(slice_names) else default_name
            ranges.append((prev, cut+1, nm))
            prev = cut+1
    if prev < len(messages):
        nm = slice_names[len(ranges)] if slice_names and len(ranges) < len(slice_names) else default_name
        ranges.append((prev, len(messages), nm))
    return ranges

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
    convo = load_convo(in_path); msgs = convo["messages"]

    slices_specs = []
    for r in args.range:
        a,b,name = parse_range(r, msgs)
        slices_specs.append((a,b,name))

    split_tokens = args.__dict__.get("split_at") or []
    if not slices_specs and split_tokens:
        ranges = build_ranges_from_split_at(split_tokens, msgs,
                                            default_name=config["default_slice_name"],
                                            slice_names=args.slice_names)
        slices_specs.extend(ranges)

    if not slices_specs:
        slices_specs = [(0, len(msgs), "whole")]

    clean_specs = []
    for a,b,name in slices_specs:
        a = max(0, min(a, len(msgs)))
        b = max(0, min(b, len(msgs)))
        if b <= a:
            continue
        clean_specs.append((a,b,name or config["default_slice_name"]))

    name_counts = {}
    enumerated = []
    for a,b,name in clean_specs:
        name_counts[name] = name_counts.get(name, 0) + 1
        nm = name if name_counts[name] == 1 else f"{name}-{name_counts[name]}"
        enumerated.append((a,b,nm))

    tags = args.tag if args.tag is not None else list(config["default_tags"])

    manifest = {
        "source_file": in_path.name,
        "conversation_id": convo["id"],
        "conversation_title": convo["title"],
        "date": convo["date"],
        "time": convo["time"],
        "slices": []
    }

    for n,(a,b,name) in enumerate(enumerated, start=1):
        slice_msgs = msgs[a:b]
        human_title = derive_title(slice_msgs) if args.auto_title else None
        fname = args.filename_template.format(
            date=convo["date"], time=convo["time"], id=convo["id"],
            slice=slugify(name, config["slug_maxlen"]), n=n
        )
        out_path = outdir / fname
        slice_obj = {
            "id": convo["id"],
            "title": convo["title"],
            "date": convo["date"],
            "time": convo["time"],
            "slice": name,
            "sequence": n,
            "tags": tags,
            "human_title": human_title,
            "range_indices": [a, b-1],
            "messages": slice_msgs
        }
        data = json.dumps(slice_obj, ensure_ascii=False, indent=2).encode("utf-8")
        checksum = sha256_bytes(data)

        entry = {
            "file": fname,
            "slice": name,
            "sequence": n,
            "approx_message_range": [a, b-1],
            "human_title": human_title
        }
        if config["include_sha256"]:
            entry["sha256"] = checksum
        manifest["slices"].append(entry)

        if not args.dry_run:
            out_path.write_bytes(data)

    if not args.dry_run:
        (outdir / "index.json").write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    print(f"Slices written: {len(enumerated)} -> {outdir}")
    for s in manifest["slices"]:
        out = f" - {s['file']}"
        if "sha256" in s:
            out += f"  [{s['sha256'][:8]}…]"
        print(out)

if __name__ == "__main__":
    main()