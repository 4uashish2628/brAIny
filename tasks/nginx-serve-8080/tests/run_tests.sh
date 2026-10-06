#!/bin/sh
fetch() { wget -qO- -T 3 "http://127.0.0.1:8080$1" 2>&1; }

home=$(fetch /)
case "$home" in
    *invig-home-7f3a*) ;;
    *) echo "FAIL: GET / did not return /srv/site/index.html"; echo "$home"; exit 1 ;;
esac

about=$(fetch /about.html)
case "$about" in
    *invig-about-c21e*) ;;
    *) echo "FAIL: GET /about.html did not return /srv/site/about.html"; echo "$about"; exit 1 ;;
esac

echo "PASS"
