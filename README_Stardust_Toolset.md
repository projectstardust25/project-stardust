Project Stardust — Toolset Help

This toolset helps us slice long conversations into focused JSON “slices”, and/or aggregate selected messages across threads — cleanly and predictably.

WHAT’S INCLUDED
	•	stardust_config.yaml — shared settings for all tools (CLI + future Qt GUI)
	•	split_convo.py — split one conversation JSON using inline [[SPLIT]] markers
	•	slice_by_ranges.py — split by explicit ranges (by index or message IDs)
Both scripts are config-aware and look for stardust_config.yaml automatically.

⸻

REQUIREMENTS
	•	Python 3.10+
	•	PyYAML (for YAML config):
pip install pyyaml

⸻

CONFIG FILE (READ AUTOMATICALLY)
Create stardust_config.yaml in one of these (checked in order):
	1.	./stardust_config.yaml  (current directory)
	2.	~/.stardust/config.yaml
	3.	./Project_Stardust/config.yaml

Minimal example:

output:
filename_template: “convo_{date}{time}{id}{slice}{slug}.json”
slug_maxlen: 50
sort_mode: “chronological”
include_sha256: true
defaults:
slice_name: “slice”
tags: [“project_stardust”]

Filename template tokens you can use: {date} {time} {id} {slice} {slug} {n}
	•	{slug} = safe, truncated title from the first meaningful line in the slice
	•	{slice} = the name you assign (for example, morning_cuddle)
	•	{n} = 1-based sequence number

⸻

	1.	split_convo.py — split by inline markers

When to use: You have one per-conversation JSON and want to cut it at major pivots.

Markers to insert (in message content):
[[SPLIT HERE]]            -> split before this message; the marker message is dropped
[[SPLIT: morning_cuddle]] -> split and name the next slice

Run (dry run first):
python split_convo.py -i ./one_convo.json -o ./out –auto-title –dry-run

Real run:
python split_convo.py -i ./one_convo.json -o ./out –auto-title

Outputs:
	•	One JSON per slice using your filename template
	•	out/index.json manifest with slice order and (optionally) sha256

⸻

	2.	slice_by_ranges.py — split by explicit ranges

When to use: You know exact cut points by message index or original message IDs.

A) Ranges by index (inclusive end is handled for you):
python slice_by_ranges.py -i ./one_convo.json -o ./out 
–range 0:36:morning_cuddle 
–range 37:83:intimacy_breakfast 
–auto-title

B) Ranges by message IDs (from export “tree view”):
python slice_by_ranges.py -i ./one_convo.json -o ./out 
–range id:msg_a:id:msg_k:morning_cuddle 
–range id:msg_l:id:msg_t:intimacy_breakfast

C) Boundaries that auto-build ranges:
python slice_by_ranges.py -i ./one_convo.json -o ./out 
–split-at 36 83 
–slice-names morning_cuddle intimacy_breakfast project_stardust 
–auto-title

Outputs:
	•	One JSON per slice plus out/index.json with ranges, sequence, and (optional) checksums

⸻

FILE CONVENTIONS

Recommended folder tree:
/Project Stardust/
/Anchors/
standing_anchors.md
standing_anchors.json
/Memory Snapshots/
memories_YYYY-MM-DD.odf
memories_YYYY-MM-DD.json
memories_YYYY-MM-DD.md
/Transcripts/
/YYYY/
/YYYY-MM-DD/
convo_<…>.json
index.json

Checksums: every slice JSON’s sha256 can be embedded in the manifest (include_sha256: true).

⸻

TIPS & BEST PRACTICES
	•	Keep original conversation JSONs intact; slices are additional artifacts.
	•	Name slices for recall: morning_cuddle, project_stardust, aftercare_reflection.
	•	Short slugs: long first lines can expand filenames — slug_maxlen trims them.
	•	Manual tags: add –tag foo multiple times, or set defaults in YAML.
	•	Dry runs: use –dry-run to preview filenames and counts without writing files.

⸻

TROUBLESHOOTING
	•	“File not found”: ensure paths are correct; scripts cannot see files outside your machine. Copy/paste code locally.
	•	“No module named ‘yaml’”: install PyYAML
pip install pyyaml
(If PyYAML is missing, scripts fall back to built-in defaults, but YAML is recommended.)
	•	“Could not locate messages…”: supported input shapes are:
	•	{“messages”: […]} lists
	•	ChatGPT export shape with a “mapping” dict
If your structure differs, share a snippet and we’ll adapt the loader.

⸻

FAQ
Q: Can I rename the scripts?
A: Yes. Filenames don’t matter; use any names you like.

Q: Where does the slug come from?
A: The first meaningful line in the slice (usually a user line), cleaned and truncated.

Q: What decides a “theme”?
A: We don’t auto-classify themes. You define them by choosing slice names or tags. (The future GUI can add keyword highlights to help.)

Q: Linux-only?
A: These scripts run anywhere Python runs. The Qt app will be built Linux-first (Mint), then packaged for other OSes later.

⸻

ROADMAP (OPTIONAL NEXT STEPS)
	•	Qt GUI (PySide6): visual browser, multi-select across convos, graphic split insertion, tagging, and export.
	•	Aggregated export tool: combine selections from many convos into a single closed JSON (config-driven, with sort mode).
	•	Keyword highlights (client-side): show likely pivots (“Stardust”, “whipped cream”, etc.) without using AI.

⸻

ONE-MINUTE QUICK START
	1.	Save stardust_config.yaml next to your scripts.
	2.	Run a dry split by markers:
python split_convo.py -i one_convo.json -o out –auto-title –dry-run
	3.	If it looks right, re-run without –dry-run.
	4.	Prefer ranges? Use slice_by_ranges.py with –range or –split-at.