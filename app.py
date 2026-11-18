import hmac
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from flask import Flask, Response, abort, jsonify, render_template, request
from mysql.connector import Error
from db import get_connection

app = Flask(__name__)

DEFAULT_DEVICE = "pi-01"
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
USE_POOL = os.environ.get("USE_POOL") == "1"

READINGS_SQL = (
    "SELECT d.device_name, r.temperature_c, r.humidity_percent, r.recorded_at "
    "FROM sensor_readings r JOIN devices d ON d.id = r.device_id "
    "WHERE d.device_name = %s ORDER BY r.recorded_at DESC LIMIT %s"
)

STATS_SQL = (
    "SELECT COUNT(*) AS n, AVG(r.temperature_c) AS avg_t, "
    "MIN(r.temperature_c) AS min_t, MAX(r.temperature_c) AS max_t, "
    "AVG(r.humidity_percent) AS avg_h "
    "FROM sensor_readings r JOIN devices d ON d.id = r.device_id "
    "WHERE d.device_name = %s "
    "AND r.recorded_at >= UTC_TIMESTAMP() - INTERVAL %s MINUTE"
)

# ---------- Actuator / Hardware Control Setup
TOKEN = os.environ.get("CONTROL_TOKEN", "")
led = None
if os.environ.get("ENABLE_LED") == "1":
    try:
        from gpiozero import LED
        led = LED(18)  # BCM 18 = physical pin 12
    except Exception as exc:
        app.logger.warning("Could not initialize GPIO LED: %s", exc)

# Extension (e): In-memory failed attempt rate limiter (per client IP)
# Window: 60 seconds, limit: 5 failures
FAILED_ATTEMPTS = defaultdict(list)
FAILED_LIMIT = 5
WINDOW_SECONDS = 60


def check_rate_limit(ip):
    now = time.time()
    # Prune old timestamps
    FAILED_ATTEMPTS[ip] = [t for t in FAILED_ATTEMPTS[ip] if now - t < WINDOW_SECONDS]
    return len(FAILED_ATTEMPTS[ip]) < FAILED_LIMIT


def record_failed_attempt(ip):
    FAILED_ATTEMPTS[ip].append(time.time())


def authorised():
    header = request.headers.get("Authorization", "")
    supplied = header[7:] if header.startswith("Bearer ") else ""
    return bool(TOKEN) and hmac.compare_digest(supplied.encode(), TOKEN.encode())


# ---------- data-access layer
def query(sql, params=()):
    """Run a parameterised read-only query and return a list of dict rows."""
    conn = get_connection("reader", pooled=USE_POOL)
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


def to_json(row):
    rec = row["recorded_at"]
    if isinstance(rec, str):
        rec_str = rec
    elif hasattr(rec, "strftime"):
        rec_str = rec.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    else:
        rec_str = str(rec)

    return {
        "device": row["device_name"],
        "temperature_c": float(row["temperature_c"]),
        "humidity_percent": float(row["humidity_percent"]),
        "recorded_at": rec_str,
    }


def rounded(x):
    return None if x is None else round(float(x), 2)


# ---------- input validation
def device_arg():
    device = request.args.get("device", DEFAULT_DEVICE)
    if not DEVICE_RE.fullmatch(device):
        abort(400, description="invalid device name")
    return device


def int_arg(name, default, lo, hi):
    raw = request.args.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        abort(400, description=f"{name} must be an integer")
    if not lo <= value <= hi:
        abort(400, description=f"{name} must be between {lo} and {hi}")
    return value


# ---------- error handling: always answer the API with JSON
@app.errorhandler(400)
def bad_request(err):
    return jsonify(error=err.description), 400


@app.errorhandler(Error)
def database_error(err):
    app.logger.error("Database error: %s", err)
    return jsonify(error="database unavailable"), 503


# ---------- routes
@app.get("/")
def dashboard():
    return render_template("index.html", device=device_arg())


@app.get("/api/health")
def health():
    query("SELECT 1 AS ok")
    return jsonify(status="ok")


@app.get("/api/devices")
def devices():
    rows = query(
        "SELECT device_name, location, sensor_type FROM devices ORDER BY device_name"
    )
    return jsonify(rows)


@app.get("/api/latest")
def latest():
    rows = query(READINGS_SQL, (device_arg(), 1))
    if not rows:
        return jsonify(error="no readings for this device"), 404
    out = to_json(rows[0])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out["age_s"] = round((now - rows[0]["recorded_at"]).total_seconds(), 1)
    return jsonify(out)


@app.get("/api/readings")
def readings():
    rows = query(READINGS_SQL, (device_arg(), int_arg("limit", 50, 1, 1000)))
    rows.reverse()  # oldest first, convenient for charts
    return jsonify([to_json(r) for r in rows])


@app.get("/api/stats")
def stats():
    device = device_arg()
    minutes = int_arg("minutes", 60, 1, 1440)
    res = query(STATS_SQL, (device, minutes))
    r = res[0] if res else {"n": 0, "avg_t": None, "min_t": None, "max_t": None, "avg_h": None}
    return jsonify(
        device=device,
        minutes=minutes,
        n=r["n"],
        avg_temperature_c=rounded(r["avg_t"]),
        min_temperature_c=rounded(r["min_t"]),
        max_temperature_c=rounded(r["max_t"]),
        avg_humidity_percent=rounded(r["avg_h"]),
    )


# Extension (a): Server-Sent Events (SSE) stream endpoint
@app.get("/api/stream")
def stream():
    device = device_arg()

    def event_stream():
        last_time = None
        while True:
            try:
                rows = query(READINGS_SQL, (device, 1))
                if rows:
                    row = rows[0]
                    if last_time != row["recorded_at"]:
                        last_time = row["recorded_at"]
                        out = to_json(row)
                        now = datetime.now(timezone.utc).replace(tzinfo=None)
                        out["age_s"] = round((now - row["recorded_at"]).total_seconds(), 1)
                        yield f"data: {json.dumps(out)}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            time.sleep(2)

    return Response(event_stream(), mimetype="text/event-stream")


# ---------- actuator control endpoints
@app.get("/api/led")
def led_state():
    if led is None:
        return jsonify(error="control disabled"), 503
    return jsonify(state="on" if led.is_lit else "off")


@app.post("/api/led")
def led_set():
    client_ip = request.remote_addr or "127.0.0.1"

    if led is None:
        return jsonify(error="control disabled"), 503

    if not check_rate_limit(client_ip):
        return jsonify(error="too many failed attempts, please wait"), 429

    if not authorised():
        record_failed_attempt(client_ip)
        return jsonify(error="unauthorised"), 401

    payload = request.get_json(silent=True) or {}
    state = payload.get("state")
    if state not in ("on", "off"):
        record_failed_attempt(client_ip)
        return jsonify(error="state must be 'on' or 'off'"), 400

    if state == "on":
        led.on()
    else:
        led.off()
    return jsonify(state="on" if led.is_lit else "off")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
