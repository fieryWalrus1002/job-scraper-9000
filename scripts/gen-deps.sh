#!/usr/bin/env bash
# Generate the full internal dependency graph for the project.
#
# Usage:
#   bash scripts/gen-deps.sh              # saves to diagrams/
#   bash scripts/gen-deps.sh DIAGRAMS     # custom output directory
#
# Prerequisites:
#   - graphviz (dot binary) installed
#   - pydeps in the project's dev dependencies
#
# Output:
#   diagrams/deps_full.dot   — raw DOT graph
#   diagrams/deps_full.png   — rendered PNG
#   diagrams/deps_edges.txt  — edge list (141 lines, LLM-friendly)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Output directory (default: diagrams/)
OUTPUT_DIR="${1:-$PROJECT_DIR/diagrams}"
mkdir -p "$OUTPUT_DIR"

# Packages to scan (each under src/<name>/)
PACKAGES=(
  job_scraper
  prefilter
  agents
  jobs_cli
  agent_eval
  utils
)

# Temporary working directory
WORK_DIR="$(mktemp -d)"
trap "rm -rf \"$WORK_DIR\"" EXIT

echo "Generating dependency graph for ${#PACKAGES[@]} packages..."

# Step 1: Generate per-package DOT files
for pkg in "${PACKAGES[@]}"; do
  echo "  $pkg"
  # --no-output prevents pydeps from writing stray SVGs to CWD.
  uv run pydeps "$PROJECT_DIR/src/$pkg" \
    --max-bacon=3 --cluster --show-dot --no-output \
    2>/dev/null > "$WORK_DIR/${pkg}.dot"
done

# Step 2: Combine into a single DOT graph
# Each pydeps output is a standalone "digraph G { ... }" block.
# Graphviz only renders the last top-level digraph it sees, so we
# strip the wrapper lines and merge everything into one graph.
{
  echo 'digraph G {'
  for f in "$WORK_DIR"/*.dot; do
    # Remove the "digraph G {" header, trailing "}", and blank lines
    grep -v '^digraph ' "$f" | grep -v '^}$' | grep -v '^$'
  done
  echo '}'
} > "$OUTPUT_DIR/deps_full.dot"

# Step 3: Extract edge list (source -> target pairs)
for f in "$WORK_DIR"/*.dot; do
  grep -E '^\s+\w+\s*->\s*\w+' "$f" | \
    sed 's/\s*\[.*\]//;s/^[[:space:]]*//'
done | sort -u > "$OUTPUT_DIR/deps_edges.txt"

# Step 4: Render PNG (dot leaks PNG binary to stdout even with -o, so suppress it)
dot -Tpng "$OUTPUT_DIR/deps_full.dot" -o "$OUTPUT_DIR/deps_full.png" >/dev/null 2>&1

echo ""
echo "Done — output in $OUTPUT_DIR/"
echo "  deps_full.dot   ($(wc -l < "$OUTPUT_DIR/deps_full.dot") lines)"
echo "  deps_full.png   ($(du -h "$OUTPUT_DIR/deps_full.png" | cut -f1))"
echo "  deps_edges.txt  ($(wc -l < "$OUTPUT_DIR/deps_edges.txt") edges)"
