#!/bin/sh
groupadd --system web
useradd --system --gid web --shell /usr/sbin/nologin deploy
chown -R deploy:web /srv/app
find /srv/app -type d -exec chmod 750 {} +
find /srv/app -type f -exec chmod 640 {} +
chmod 750 /srv/app/bin/start.sh
