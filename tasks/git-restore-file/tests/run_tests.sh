#!/bin/sh
# Traps: `git revert` of the cleanup commit also undoes its README change;
# reset/rebase drops commits; restoring from the wrong commit gives the old prices.
cd /app/repo 2>/dev/null || { echo "FAIL: /app/repo is missing"; exit 1; }

expected_pricing='sku,price
MUG,15.00
LAMP,42.50
BOOK,25.00'
[ "$(git show HEAD:pricing.csv 2>/dev/null)" = "$expected_pricing" ] \
    || { echo "FAIL: pricing.csv in HEAD is missing or has the wrong content"; git show HEAD:pricing.csv 2>&1; exit 1; }

expected_readme='# Shop

Internal tools for the shop team.'
[ "$(git show HEAD:README.md)" = "$expected_readme" ] || { echo "FAIL: README.md was changed"; exit 1; }
git cat-file -e HEAD:CHANGELOG.md 2>/dev/null || { echo "FAIL: CHANGELOG.md is gone"; exit 1; }

subjects=$(git log --format=%s main)
for s in "add README" "add pricing table" "update lamp price, add book" "cleanup and docs" "add changelog"; do
    echo "$subjects" | grep -qxF "$s" || { echo "FAIL: commit '$s' is no longer in history"; exit 1; }
done
[ "$(git rev-list --count main)" -ge 6 ] || { echo "FAIL: the restore was not committed"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "FAIL: working tree is not clean"; git status --short; exit 1; }
echo "PASS"
