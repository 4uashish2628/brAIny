#!/bin/sh
set -e
mkdir -p /app/repo && cd /app/repo
git init -q -b main
commit() { git add -A && git commit -q -m "$1"; }

printf '# Shop\n\nInternal tools.\n' > README.md;                            commit "add README"
printf 'sku,price\nMUG,15.00\nLAMP,40.00\n' > pricing.csv;                 commit "add pricing table"
printf 'sku,price\nMUG,15.00\nLAMP,42.50\nBOOK,25.00\n' > pricing.csv;     commit "update lamp price, add book"
git rm -q pricing.csv
printf '# Shop\n\nInternal tools for the shop team.\n' > README.md;         commit "cleanup and docs"
printf '## 1.1\n- docs\n' > CHANGELOG.md;                                    commit "add changelog"
