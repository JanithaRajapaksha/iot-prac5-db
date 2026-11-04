import argparse
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")  # Run headlessly without display
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from db import get_connection


def main():
    parser = argparse.ArgumentParser(
        description="Plot sensor readings for a device over the last 30 minutes."
    )
    parser.add_argument("--device", default="pi-01", help="Device name to query")
    parser.add_argument(
        "--output", default="readings.png", help="Path to save the output PNG plot"
    )
    args = parser.parse_args()

    conn = get_connection("reader")
    cur = conn.cursor()

    query = """
        SELECT r.recorded_at, r.temperature_c, r.humidity_percent
        FROM sensor_readings r
        JOIN devices d ON d.id = r.device_id
        WHERE d.device_name = %s
          AND r.recorded_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 30 MINUTE)
        ORDER BY r.recorded_at ASC;
    """
    cur.execute(query, (args.device,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    print(f"Number of rows plotted: {len(rows)}")
    if not rows:
        print(f"No telemetry found for device '{args.device}' in the last 30 minutes.")
        return

    timestamps = [r[0] for r in rows]
    temperatures = np.array([float(r[1]) for r in rows])
    humidities = np.array([float(r[2]) for r in rows])

    # Compute 5-point moving average
    temp_ma = np.convolve(temperatures, np.ones(5) / 5, mode="valid")
    hum_ma = np.convolve(humidities, np.ones(5) / 5, mode="valid")
    ma_timestamps = timestamps[2 : len(timestamps) - 2] if len(timestamps) >= 5 else []

    # Outliers: > 2 standard deviations from device sample mean
    temp_mean, temp_std = np.mean(temperatures), np.std(temperatures)
    hum_mean, hum_std = np.mean(humidities), np.std(humidities)

    temp_outlier_idx = np.where(np.abs(temperatures - temp_mean) > 2 * temp_std)[0] if temp_std > 0 else []
    hum_outlier_idx = np.where(np.abs(humidities - hum_mean) > 2 * hum_std)[0] if hum_std > 0 else []

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # Temperature subplot
    ax1.plot(timestamps, temperatures, "b.-", alpha=0.4, label="Raw Temperature")
    if len(ma_timestamps) == len(temp_ma):
        ax1.plot(ma_timestamps, temp_ma, "r-", linewidth=2, label="5-Point Moving Avg")
    if len(temp_outlier_idx) > 0:
        ax1.scatter(
            [timestamps[i] for i in temp_outlier_idx],
            temperatures[temp_outlier_idx],
            color="red",
            s=70,
            edgecolor="black",
            zorder=5,
            label="Outlier (> 2σ)",
        )
    ax1.set_ylabel("Temperature (°C)", fontsize=11)
    ax1.set_title(f"Telemetry for Device: {args.device} (Last 30 Minutes)", fontsize=13)
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend(loc="upper left")

    # Humidity subplot
    ax2.plot(timestamps, humidities, "g.-", alpha=0.4, label="Raw Humidity")
    if len(ma_timestamps) == len(hum_ma):
        ax2.plot(ma_timestamps, hum_ma, "m-", linewidth=2, label="5-Point Moving Avg")
    if len(hum_outlier_idx) > 0:
        ax2.scatter(
            [timestamps[i] for i in hum_outlier_idx],
            humidities[hum_outlier_idx],
            color="purple",
            s=70,
            edgecolor="black",
            zorder=5,
            label="Outlier (> 2σ)",
        )
    ax2.set_ylabel("Relative Humidity (%)", fontsize=11)
    ax2.set_xlabel("Time (UTC)", fontsize=11)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.legend(loc="upper left")

    fig.tight_layout()
    plt.savefig(args.output, dpi=150)
    print(f"Plot saved successfully to {args.output}")


if __name__ == "__main__":
    main()

