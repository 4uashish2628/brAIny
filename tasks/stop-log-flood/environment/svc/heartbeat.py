import time

while True:
    with open("/var/log/app/heartbeat.log", "w") as f:
        f.write(f"alive {int(time.time())}\n")
    time.sleep(2)
