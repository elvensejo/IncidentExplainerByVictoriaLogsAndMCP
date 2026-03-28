import time
import requests

url = "http://localhost:9428/insert/jsonline"

with open("logs/access.log", "r") as f:
    f.seek(0, 2) # Идем в конец файла
    while True:
        line = f.readline()
        if not line:
            time.sleep(0.1)
            continue
        data = {"message": line.strip(), "service": "nginx"}
        requests.post(url, json=data)
        print(f"Sent: {line.strip()}")