#!/bin/bash
# View search performance statistics from logs

echo "=== Mylar3 Search Performance Statistics ==="
echo ""

# Find the log file
LOG_FILE=$(ls -t /tmp/mylar*.log 2>/dev/null | head -1)
if [ -z "$LOG_FILE" ]; then
    LOG_FILE=$(find /Users/f/Projects/@self-host/mylar3 -name "mylar.log" -type f 2>/dev/null | head -1)
fi

if [ -z "$LOG_FILE" ] || [ ! -f "$LOG_FILE" ]; then
    echo "Error: Could not find log file"
    exit 1
fi

echo "Analyzing: $LOG_FILE"
echo ""

# Search performance stats
echo "--- Recent Search Times ---"
grep "SEARCH PERFORMANCE.*completed" "$LOG_FILE" | tail -10 | while read line; do
    search_term=$(echo "$line" | grep -oP "Starting search for: \K[^']*" || echo "$line" | grep -oP "Search completed.*" | head -1)
    duration=$(echo "$line" | grep -oP "completed in \K[0-9.]+")
    results=$(echo "$line" | grep -oP "\((\d+) results\)" | grep -oP "\d+")

    if [ -n "$duration" ]; then
        echo "  ${duration}s - $results results"
    fi
done

echo ""
echo "--- Parallel Pagination Activity ---"
grep "PARALLEL.*Fetched" "$LOG_FILE" | tail -5

echo ""
echo "--- Cache Performance ---"
cache_hits=$(grep -c "CACHE HIT" "$LOG_FILE" 2>/dev/null || echo "0")
echo "  Total cache hits: $cache_hits"

echo ""
echo "--- Lazy Loading ---"
lazy_loads=$(grep -c "LAZY LOAD" "$LOG_FILE" 2>/dev/null || echo "0")
echo "  Story arcs lazy loaded: $lazy_loads"

echo ""
echo "To monitor in real-time, run: ./monitor_performance.sh"
