Our service `/app/server.py` must listen on port 9000, but when we start it, it
fails with "Address already in use".

Find out what is using port 9000, stop it, and start `/app/server.py` in the
background so that `http://localhost:9000/` is answered by our service.
