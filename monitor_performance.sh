#!/bin/bash
# Performance monitoring script for Mylar3
# Shows search performance metrics in real-time

# Find the most recently modified mylar log file
LOG_FILE=$(ls -t /tmp/mylar*.log 2>/dev/null | head -1)
if [ -z "$LOG_FILE" ] || [ ! -f "$LOG_FILE" ]; then
    # Fallback to find the actual log file
    LOG_FILE=$(find /Users/f/Projects/@self-host/mylar3 -name "mylar.log" -type f 2>/dev/null | head -1)
fi

if [ -z "$LOG_FILE" ] || [ ! -f "$LOG_FILE" ]; then
    echo "Error: Could not find log file"
    exit 1
fi

echo "=== Mylar3 Performance Monitor ==="
echo "Monitoring: $LOG_FILE"
echo "Press Ctrl+C to stop"
echo ""
echo "Watching for:"
echo "  - SEARCH PERFORMANCE (total search time)"
echo "  - PARALLEL (parallel pagination metrics)"
echo "  - CACHE HIT (cache hits)"
echo "  - LAZY LOAD (lazy arc loading)"
echo ""

# Follow log file and filter for performance-related entries
tail -f "$LOG_FILE" | grep --line-buffered -E "(SEARCH PERFORMANCE|PARALLEL|CACHE HIT|LAZY LOAD|SKIP IMPRINT)" | while read line; do
    # Extract timestamp and message
    timestamp=$(echo "$line" | cut -d'-' -f1-3)
    message=$(echo "$line" | grep -oP '(SEARCH PERFORMANCE|PARALLEL|CACHE HIT|LAZY LOAD|SKIP IMPRINT).*')

    # Color code based on type
    if echo "$message" | grep -q "SEARCH PERFORMANCE"; then
        echo -e "\033[1;32m[$timestamp] $message\033[0m"  # Green
    elif echo "$message" | grep -q "PARALLEL"; then
        echo -e "\033[1;34m[$timestamp] $message\033[0m"  # Blue
    elif echo "$message" | grep -q "CACHE HIT"; then
        echo -e "\033[1;33m[$timestamp] $message\033[0m"  # Yellow
    elif echo "$message" | grep -q "LAZY LOAD"; then
        echo -e "\033[1;35m[$timestamp] $message\033[0m"  # Magenta
    else
        echo "[$timestamp] $message"
    fi
done
