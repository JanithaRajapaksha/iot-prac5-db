import time
from datetime import datetime, timedelta
from db import get_connection

N = 5000
SQL = (
    "INSERT INTO bench_readings "
    "(device_id, temperature_c, humidity_percent, recorded_at) "
    "VALUES (%s, %s, %s, %s)"
)
base = datetime(2026, 1, 1)
rows = [
    (1, 25 + (i % 100) / 10, 60 + (i % 200) / 10, base + timedelta(seconds=i))
    for i in range(N)
]


def run(batch):
    conn = get_connection("writer")
    cur = conn.cursor()
    cur.execute("DELETE FROM bench_readings")
    conn.commit()
    t0 = time.perf_counter()
    for i in range(0, N, batch):
        cur.executemany(SQL, rows[i : i + batch])
        conn.commit()  # one commit per batch
    elapsed = time.perf_counter() - t0
    cur.close()
    conn.close()
    return elapsed


if __name__ == "__main__":
    for batch in (1, 10, 100, 1000):
        t = run(batch)
        print(f"batch={batch:5d} time={t:7.2f} s rate={N / t:9.0f} rows/s")

