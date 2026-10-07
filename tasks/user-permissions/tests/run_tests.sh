#!/bin/sh
# Traps: chmod -R 640 makes directories untraversable; chmod -R 750 leaves files
# executable; the hidden file data/.keep and nested static/css are easy to miss.
id deploy >/dev/null 2>&1 || { echo "FAIL: user deploy does not exist"; exit 1; }
id -nG deploy | tr ' ' '\n' | grep -qx web || { echo "FAIL: deploy is not in group web"; exit 1; }

fail=0
check() {
    actual=$(stat -c '%U:%G %a' "$1")
    if [ "$actual" != "deploy:web $2" ]; then
        echo "FAIL: $1 is '$actual', expected 'deploy:web $2'"; fail=1
    fi
}
for d in $(find /srv/app -type d); do check "$d" 750; done
for f in $(find /srv/app -type f); do
    if [ "$f" = /srv/app/bin/start.sh ]; then check "$f" 750; else check "$f" 640; fi
done
[ $fail -eq 0 ] && echo "PASS"
exit $fail
