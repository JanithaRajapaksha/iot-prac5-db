import argparse
import signal
import time
from collections import deque
from datetime import datetime, timezone
from mysql.connector import Error
from db import get_connection
from sensors import DHTSensor, SimulatedSensor

INSERT_SQL = (
    "INSERT INTO sensor_readings "
    "(device_id, temperature_c, humidity_percent, recorded_at) "
    "VALUES (%s, %s, %s, %s) "
    "ON DUPLICATE KEY UPDATE id = id"  # makes retries idempotent
)

running = True


def stop(signum, frame):
    global running
    running = False


def valid(temp, hum):
    return -40 <= temp <= 80 and 0 <= hum <= 100


def get_device_id(conn, name):
    cur = conn.cursor()
    cur.execute("SELECT id FROM devices WHERE device_name = %s", (name,))
    row = cur.fetchone()
    cur.close()
    if row is None:
        raise SystemExit(f"Device '{name}' is not registered in the database.")
    return row[0]


def try_flush(conn, rows):
    """Write rows in a single transaction. Return True on success."""
    try:
        cur = conn.cursor()
        cur.executemany(INSERT_SQL, rows)
        conn.commit()
        cur.close()
        return True
    except Error as err:
        print(" DB error:", err)
        try:
            conn.rollback()
        except Error:
            pass
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="pi-01")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds")
    ap.add_argument("--batch", type=int, default=10, help="rows per transaction")
    ap.add_argument("--sensor", choices=["sim", "dht"], default="sim", help="Sensor source: 'sim' or 'dht'")
    ap.add_argument("--pin", default="D4", help="Raspberry Pi GPIO pin for DHT11 (default: D4)")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    sensor = SimulatedSensor() if args.sensor == "sim" else DHTSensor(pin_name=args.pin)
    conn = get_connection("writer")
    device_id = get_device_id(conn, args.device)
    buffer = deque(maxlen=10000)  # bounded: oldest rows dropped if full
    stats = {"stored": 0, "failed_reads": 0, "rejected": 0}
    backoff, next_attempt = 1, 0.0
    next_sample = time.monotonic()
    print(f"Logging started for device '{args.device}' (sensor={args.sensor}). Press Ctrl+C to stop.")

    try:
        while running:
            reading = sensor.read()
            if reading is None:
                stats["failed_reads"] += 1
            elif not valid(*reading):
                stats["rejected"] += 1
            else:
                now = datetime.now(timezone.utc).replace(tzinfo=None)  # UTC
                buffer.append((device_id, reading[0], reading[1], now))

            if len(buffer) >= args.batch and time.monotonic() >= next_attempt:
                try:
                    if not conn.is_connected():
                        conn = get_connection("writer")
                    ok = try_flush(conn, list(buffer))
                except Error as err:
                    print(" Cannot connect:", err)
                    ok = False

                if ok:
                    stats["stored"] += len(buffer)
                    print(f"Stored {len(buffer)} rows (total {stats['stored']})")
                    buffer.clear()
                    backoff = 1
                else:
                    print(f" Retry in {backoff} s; {len(buffer)} rows buffered")
                    next_attempt = time.monotonic() + backoff
                    backoff = min(backoff * 2, 60)

            next_sample += args.interval
            time.sleep(max(0.0, next_sample - time.monotonic()))

        # clean shutdown: one last attempt to write what is still buffered
        if buffer:
            try:
                if try_flush(get_connection("writer"), list(buffer)):
                    stats["stored"] += len(buffer)
                    buffer.clear()
            except Error as err:
                print("Final flush failed:", err)

        print("Summary:", stats, "| unsent:", len(buffer))
    finally:
        # Release GPIO pin back to the OS to avoid 'Unable to set line' errors on subsequent runs
        if hasattr(sensor, "exit"):
            sensor.exit()


if __name__ == "__main__":
    main()

