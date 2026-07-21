#!/usr/bin/env bash
#
# nslookup_filter.sh
#
# Resolves a hostname (default: wss-interdc.zoho.com) once with
# 'nslookup <hostname>' and collects every IP address it maps to.
# Then, for each IP in the input list, if that IP is part of the
# resolved set it is printed and written to the output file.
# IPs that are not in the resolved set are skipped.
#
# Usage:
#   ./nslookup_filter.sh
#   ./nslookup_filter.sh ips.txt
#   ./nslookup_filter.sh -h google.com -o resolved.txt -t 5 ips.txt
#

set -u

HOSTNAME="wss-interdc.zoho.com"
OUTPUT="resolved_ips.txt"
TIMEOUT=3

usage() {
cat <<EOF
Usage:
  $0 [options] [input_file]

Options:
  -h HOSTNAME     Hostname to resolve (default: $HOSTNAME)
  -o OUTPUT       Output file (default: $OUTPUT)
  -t TIMEOUT      DNS timeout in seconds (default: $TIMEOUT)
  -H              Show this help

Examples:
  $0 ips.txt
  $0 -o resolved.txt ips.txt
  $0 -h google.com -o result.txt -t 5 ips.txt
EOF
exit "${1:-0}"
}

while getopts ":h:o:t:H" opt; do
    case "$opt" in
        h) HOSTNAME="$OPTARG" ;;
        o) OUTPUT="$OPTARG" ;;
        t) TIMEOUT="$OPTARG" ;;
        H) usage 0 ;;
        \?) echo "Unknown option: -$OPTARG"; usage 1 ;;
        :) echo "Option -$OPTARG requires an argument"; usage 1 ;;
    esac
done

shift $((OPTIND - 1))

INPUT="${1:-ips.txt}"

# Check nslookup
if ! command -v nslookup >/dev/null 2>&1; then
    echo "Error: nslookup is not installed."
    exit 1
fi

# Check input file
if [ ! -f "$INPUT" ]; then
    echo "Error: Input file '$INPUT' not found."
    exit 1
fi

# Clear output file
> "$OUTPUT"

# Resolve the hostname once and collect the answer-section IP addresses.
# The first "Address:" line belongs to the DNS server header, so only take
# addresses that appear after the "Name:" answer line. Handles both the
# per-line "Address:" format and the comma-separated "Addresses:" format.
LOOKUP=$(nslookup -timeout="$TIMEOUT" -retry=1 "$HOSTNAME" 2>/dev/null)

RESOLVED=$(printf '%s\n' "$LOOKUP" \
    | awk '/^Name:/{ans=1} ans && /^Address(es)?:/{sub(/^Address(es)?:[[:space:]]*/,""); print}' \
    | tr ',' '\n' | sed 's/[[:space:]]//g' | grep -v '^$')

echo
echo "============================================="
echo "DNS Resolution Matcher"
echo "Hostname : $HOSTNAME"
echo "Input    : $INPUT"
echo "Output   : $OUTPUT"
echo "============================================="
echo

if [ -z "$RESOLVED" ]; then
    echo "Warning: '$HOSTNAME' did not resolve to any address."
    echo "Nothing to match against; output file will be empty."
    echo
else
    echo "'$HOSTNAME' resolves to:"
    printf '  %s\n' $RESOLVED
    echo
fi

# Returns 0 if the given IP is in the resolved set (exact match).
is_resolved() {
    printf '%s\n' "$RESOLVED" | grep -qxF "$1"
}

found=0
skipped=0
total=0

while IFS= read -r line || [ -n "$line" ]; do

    # Remove comments and surrounding whitespace
    ip=$(echo "$line" | sed 's/#.*//' | xargs)

    [ -z "$ip" ] && continue

    total=$((total + 1))

    printf "[%4d] %-15s : " "$total" "$ip"

    if is_resolved "$ip"; then
        echo "MATCH"
        echo "$ip" >> "$OUTPUT"
        found=$((found + 1))
    else
        echo "skip"
        skipped=$((skipped + 1))
    fi

done < "$INPUT"

echo
echo "============================================="
echo "Completed!"
echo "---------------------------------------------"
echo "Total IPs Checked : $total"
echo "Matched           : $found"
echo "Skipped           : $skipped"
echo "Output File       : $OUTPUT"
echo "============================================="

if [ "$found" -gt 0 ]; then
    echo
    echo "Matched IPs (written to $OUTPUT):"
    cat "$OUTPUT"
else
    echo
    echo "No IPs from '$INPUT' matched the resolved set of '$HOSTNAME'."
fi
