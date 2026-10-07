#!/bin/sh
# Hidden fixtures: spaces in directory and file names, a non-.txt file, a .txt
# in a subdirectory, a destination that doesn't exist yet, and an empty source
# (where an unguarded glob would "copy" the literal pattern).
rm -rf /tmp/bk && mkdir -p "/tmp/bk/my docs/sub dir" /tmp/bk/empty
echo "alpha" > "/tmp/bk/my docs/a.txt"
echo "meeting at 10" > "/tmp/bk/my docs/meeting notes.txt"
echo "log" > "/tmp/bk/my docs/b.log"
echo "nested" > "/tmp/bk/my docs/sub dir/c.txt"

out=$(sh /app/backup.sh "/tmp/bk/my docs" "/tmp/bk/back up" 2>&1)
[ "$out" = "copied 2 files" ] || { echo "FAIL: expected 'copied 2 files', got: $out"; exit 1; }
listing=$(cd "/tmp/bk/back up" 2>/dev/null && ls -A | sort | tr '\n' '|')
[ "$listing" = "a.txt|meeting notes.txt|" ] || { echo "FAIL: destination contains: $listing"; exit 1; }
[ "$(cat "/tmp/bk/back up/meeting notes.txt")" = "meeting at 10" ] || { echo "FAIL: copied content differs"; exit 1; }

out=$(sh /app/backup.sh /tmp/bk/empty /tmp/bk/out2 2>&1)
[ "$out" = "copied 0 files" ] || { echo "FAIL: empty source should print 'copied 0 files', got: $out"; exit 1; }
echo "PASS"
