#!/usr/bin/env bash
set -euo pipefail

Config: adjust defaults here if you want

IN="./one_convo.json"
OUT="./out"

usage() {
cat <<EOF
Project Stardust — quick commands

Usage:
$0 markers [--in FILE] [--out DIR] [--auto-title] [--dry-run]
$0 index [--in FILE] [--out DIR] START:END:NAME [START:END:NAME ...]
$0 ids [--in FILE] [--out DIR] id:START:id:END:NAME [more ranges...]

Examples:
$0 markers --in one_convo.json --out out --auto-title --dry-run
$0 index --in one_convo.json --out out 0:36:morning_cuddle 37:83:intimacy
$0 ids --in one_convo.json --out out id:msg_a:id:msg_k:tech

Notes:

Reads stardust_config.yaml automatically if present.

CLI flags override config.
EOF
}

parse --in/--out anywhere

parse_common() {
while [[ $# -gt 0 ]]; do
case "$1" in
--in) IN="$2"; shift 2 ;;
--out) OUT="$2"; shift 2 ;;
*) break ;;
esac
done
}

cmd="${1:-help}"
shift || true

case "$cmd" in
help|-h|--help) usage ;;

markers)
parse_common "$@"
python split_convo.py -i "$IN" -o "$OUT" "${@}"
;;

index)
parse_common "$@"
ARGS=()
for tok in "$@"; do
[[ "$tok" == --* ]] && continue
ARGS+=( --range "$tok" )
done
python slice_by_ranges.py -i "$IN" -o "$OUT" "${ARGS[@]}"
;;

ids)
parse_common "$@"
ARGS=()
for tok in "$@"; do
[[ "$tok" == --* ]] && continue
ARGS+=( --range "$tok" )
done
python slice_by_ranges.py -i "$IN" -o "$OUT" "${ARGS[@]}"
;;

*)
echo "Unknown command: $cmd"
usage
exit 2
;;
esac
