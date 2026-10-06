A static website lives in `/srv/site`.

Configure nginx to serve that directory on port 8080, so that
`http://localhost:8080/` returns `/srv/site/index.html` and other pages in the
directory (for example `/about.html`) are served too. Make sure nginx is
running when you are done.
