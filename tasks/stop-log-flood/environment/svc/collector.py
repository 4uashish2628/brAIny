import time

line = "DEBUG metrics sample " + "x" * 200 + "\n"
with open("/var/log/app/collector.log", "a") as f:
    while True:
        f.write(line * 200)
        f.flush()
        time.sleep(0.2)
