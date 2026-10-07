Set up a service account for the app in `/srv/app`:

1. Create a system user `deploy` that is a member of a group `web`.
2. Make `/srv/app` and everything in it owned by user `deploy` and group `web`.
3. Directories must be accessible by owner and group only (mode 750). Files
   must be readable by owner and group only (mode 640), except
   `/srv/app/bin/start.sh`, which must also be executable by owner and group (750).
