#!/usr/bin/env bash
#
# nslookup_filter.sh
#
# Resolves a hostname (default: wss-interdc.zoho.com) with:
#
#     nslookup <hostname>
#
# and collects every IP address it maps to. Then, for each IP in the input
# list, if that IP appears in the resolved set, the IP is written to the
# output file. IPs that are not part of the resolved set are skipped.
#
# Usage:
#   ./nslookup_filter.sh [-h hostname] [-o output_file] [input_file]
#
# Examples:
#   ./nslookup_filter.sh ips.txt
#   ./nslookup_filter.sh -o matched.txt ips.txt
#   ./nslookup_filter.sh -h wss-interdc.zoho.com -o matched.txt ips.txt
#
# Input file format: one IP per line. Blank lines and lines starting with '#'
# are ignored.

set -u

HOSTNAME="wss-interdc.zoho.com"
OUTPUT="matched_ips.txt"

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while getopts ":h:o:H" opt; do
    case "$opt" in
        h) HOSTNAME="$OPTARG" ;;
        o) OUTPUT="$OPTARG" ;;
        H) usage 0 ;;
        \?) echo "Unknown option: -$OPTARG" >&2; usage 1 ;;
        :)  echo "Option -$OPTARG requires an argument" >&2; usage 1 ;;
    esac
done
shift $((OPTIND - 1))

INPUT="${1:-ips.txt}"

if ! command -v nslookup >/dev/null 2>&1; then
    echo "Error: nslookup is not installed or not in PATH." >&2
    exit 1
fi

if [ ! -r "$INPUT" ]; then
    echo "Error: cannot read input file '$INPUT'." >&2
    exit 1
fi

# Resolve the hostname once and extract the answer-section IP addresses.
# The first "Address:" line belongs to the DNS server header, so we only
# take addresses that follow the "Name:" answer line.
lookup="$(nslookup "$HOSTNAME" 2>/dev/null)"
resolved="$(printf '%s\n' "$lookup" \
    | awk '/^Name:/{ans=1} ans && /^Address(es)?:/{sub(/^Address(es)?:[[:space:]]*/,""); print}' \
    | tr ',' '\n' | sed 's/[[:space:]]//g' | grep -v '^$')"

if [ -z "$resolved" ]; then
    echo "Warning: '$HOSTNAME' did not resolve to any address; nothing to match." >&2
fi

# Start with a clean output file.
: > "$OUTPUT"

found=0
total=0
while IFS= read -r line || [ -n "$line" ]; do
    # Strip inline comments/whitespace and skip blanks.
    ip="$(printf '%s' "$line" | sed 's/#.*//' | tr -d '[:space:]')"
    [ -z "$ip" ] && continue
    total=$((total + 1))

    # Print the IP only if it is present in the resolved set (exact match).
    if printf '%s\n' "$resolved" | grep -qxF "$ip"; then
        echo "$ip" >> "$OUTPUT"
        found=$((found + 1))
    fi
done < "$INPUT"

echo "Checked $total IP(s); $found matched '$HOSTNAME'. Results in '$OUTPUT'." >&2
