#!/bin/sh
cat > /etc/nginx/conf.d/default.conf <<'CONF'
server {
    listen 8080;
    root /srv/site;
    index index.html;
}
CONF
nginx -t && nginx
sleep 1
