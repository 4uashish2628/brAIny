`/app/backup.sh` is run as `sh /app/backup.sh SOURCE_DIR DEST_DIR`. It should
copy every `*.txt` file directly inside SOURCE_DIR (not in subdirectories) into
DEST_DIR, creating DEST_DIR if it doesn't exist, and then print exactly
`copied N files`.

It breaks on real-world paths. Fix it so it works for any directory and file
names, including names with spaces.
