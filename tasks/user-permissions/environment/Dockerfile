FROM debian:bookworm-slim
RUN mkdir -p /srv/app/bin /srv/app/config /srv/app/static/css /srv/app/data \
 && printf '#!/bin/sh\necho starting\n' > /srv/app/bin/start.sh \
 && printf '[app]\nport = 8080\n' > /srv/app/config/app.ini \
 && printf '<h1>hi</h1>\n' > /srv/app/static/index.html \
 && printf 'body {}\n' > /srv/app/static/css/site.css \
 && touch /srv/app/data/.keep \
 && chmod -R a+rwX /srv/app
CMD ["sleep", "infinity"]
