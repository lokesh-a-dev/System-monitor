#!/usr/bin/env bash
#
# nslookup_filter.sh
#
# For each IP in the input list, treat that IP as a DNS server and ask it to
# resolve a hostname (default: wss-interdc.zoho.com) using:
#
#     nslookup <hostname> <ip>
#
# If the server successfully resolves the hostname, the IP is written to the
# output file. IPs that fail (timeout, SERVFAIL, refused, no answer) are
# skipped silently.
#
# Usage:
#   ./nslookup_filter.sh [-h hostname] [-o output_file] [-t timeout] [input_file]
#
# Examples:
#   ./nslookup_filter.sh ips.txt
#   ./nslookup_filter.sh -o resolved.txt ips.txt
#   ./nslookup_filter.sh -h wss-interdc.zoho.com -t 3 -o resolved.txt ips.txt
#
# Input file format: one IP per line. Blank lines and lines starting with '#'
# are ignored.

set -u

HOSTNAME="wss-interdc.zoho.com"
OUTPUT="resolved_ips.txt"
TIMEOUT=3

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while getopts ":h:o:t:H" opt; do
    case "$opt" in
        h) HOSTNAME="$OPTARG" ;;
        o) OUTPUT="$OPTARG" ;;
        t) TIMEOUT="$OPTARG" ;;
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

# Start with a clean output file.
: > "$OUTPUT"

# Returns 0 if <server_ip> resolves $HOSTNAME, non-zero otherwise.
resolves() {
    local server="$1"
    local out
    # -timeout limits per-query wait; -retry avoids long hangs on dead servers.
    out=$(nslookup -timeout="$TIMEOUT" -retry=1 "$HOSTNAME" "$server" 2>/dev/null) || return 1
    # A successful answer contains a "Name:" line in the answer section
    # (the server header only has "Server:"/"Address:" lines). Guard against
    # NXDOMAIN / "can't find" responses that some resolvers still exit 0 on.
    if printf '%s\n' "$out" | grep -qiE "can't find|NXDOMAIN|SERVFAIL|REFUSED|no servers could be reached"; then
        return 1
    fi
    printf '%s\n' "$out" | grep -qiE "^Name:[[:space:]]*$HOSTNAME"
}

found=0
total=0
while IFS= read -r line || [ -n "$line" ]; do
    # Strip inline whitespace/comments and skip blanks.
    ip="$(printf '%s' "$line" | sed 's/#.*//' | tr -d '[:space:]')"
    [ -z "$ip" ] && continue
    total=$((total + 1))

    if resolves "$ip"; then
        echo "$ip" >> "$OUTPUT"
        found=$((found + 1))
    fi
done < "$INPUT"

echo "Checked $total IP(s); $found resolved '$HOSTNAME'. Results in '$OUTPUT'." >&2
