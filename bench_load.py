#!/usr/bin/env python3
"""
bench_load.py: Lightweight concurrent HTTP load benchmarker matching ApacheBench (ab).
Usage: python3 bench_load.py http://localhost:5000/api/latest?device=pi-01 -n 500 -c 10
"""
import argparse
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import numpy as np


def fetch(url):
    t0 = time.perf_counter()
    status = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bench-loader"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            _ = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = 0
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return (status == 200), elapsed_ms


def run_benchmark(url, n=500, c=10):
    print(f"Benchmarking {url} with {n} requests, concurrency {c}...")
    start_time = time.perf_counter()
    latencies = []
    success_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=c) as executor:
        results = list(executor.map(lambda _: fetch(url), range(n)))

    total_time_s = time.perf_counter() - start_time
    for ok, lat in results:
        latencies.append(lat)
        if ok:
            success_count += 1
        else:
            failed_count += 1

    latencies.sort()
    rps = n / total_time_s if total_time_s > 0 else 0
    mean_lat = float(np.mean(latencies)) if latencies else 0
    p95_lat = float(np.percentile(latencies, 95)) if latencies else 0

    print("--------------------------------------------------")
    print(f"Total time taken:     {total_time_s:.3f} seconds")
    print(f"Completed requests:   {len(latencies)}")
    print(f"Failed requests:      {failed_count}")
    print(f"Requests per second:  {rps:.2f} [#/sec]")
    print(f"Time per request:     {mean_lat:.2f} [ms] (mean)")
    print(f"95% percentile:       {p95_lat:.2f} [ms]")
    print("--------------------------------------------------")
    return {
        "rps": round(rps, 2),
        "mean_ms": round(mean_lat, 2),
        "p95_ms": round(p95_lat, 2),
        "failed": failed_count,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load benchmark runner")
    parser.add_argument("url", help="Target URL")
    parser.add_argument("-n", "--requests", type=int, default=500, help="Total requests")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="Concurrency")
    args = parser.parse_args()
    run_benchmark(args.url, n=args.requests, c=args.concurrency)
