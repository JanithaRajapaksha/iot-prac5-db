import random


class SimulatedSensor:
    """Bounded random walk with occasional failed reads."""

    def __init__(self, fail_rate=0.05):
        self.t, self.h, self.fail_rate = 28.0, 65.0, fail_rate

    def read(self):
        if random.random() < self.fail_rate:
            return None
        self.t = min(max(self.t + random.gauss(0, 0.3), 20.0), 40.0)
        self.h = min(max(self.h + random.gauss(0, 0.8), 30.0), 95.0)
        return round(self.t, 2), round(self.h, 2)


class DHTSensor:
    """DHT11 via the Adafruit library (install as in Practical 03)."""

    def __init__(self, pin_name="D4"):
        import board
        import adafruit_dht

        self.dev = adafruit_dht.DHT11(getattr(board, pin_name))

    def read(self):
        try:
            return float(self.dev.temperature), float(self.dev.humidity)
        except (RuntimeError, TypeError):
            return None

