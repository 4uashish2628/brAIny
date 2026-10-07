#!/bin/sh
cat > /app/backup.sh <<'SH'
#!/bin/sh
src=$1
dest=$2
mkdir -p "$dest"
count=0
for f in "$src"/*.txt; do
  [ -f "$f" ] || continue   # no match leaves the pattern itself in $f
  cp "$f" "$dest"/
  count=$((count + 1))
done
echo "copied $count files"
SH
