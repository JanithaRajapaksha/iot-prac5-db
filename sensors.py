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

    def exit(self):
        """No-op for simulated sensor."""
        pass

    def close(self):
        self.exit()


class DHTSensor:
    """Hardware DHT11 sensor reader using Adafruit CircuitPython DHT library."""

    def __init__(self, pin_name="D4"):
        try:
            import board
            import adafruit_dht
        except ImportError as exc:
            raise RuntimeError(
                "Packages 'board' and 'adafruit-circuitpython-dht' are required on the Raspberry Pi.\n"
                "Install them using:\n"
                "  sudo apt install -y libgpiod2\n"
                "  pip install adafruit-circuitpython-dht"
            ) from exc

        pin = getattr(board, pin_name, None)
        if pin is None:
            raise ValueError(f"Pin '{pin_name}' not found on board module.")

        self.pin_name = pin_name
        # use_pulseio=False prevents timing lockouts on Linux GPIO
        self.dev = adafruit_dht.DHT11(pin, use_pulseio=False)
        print(f"Initialized physical DHT11 on GPIO pin '{pin_name}' (use_pulseio=False).")

    def read(self):
        """Return (temperature_c, humidity_percent) or None if read fails."""
        try:
            temp = self.dev.temperature
            hum = self.dev.humidity
            # Only return data if both temperature and humidity returned valid numbers
            if temp is not None and hum is not None:
                return round(float(temp), 2), round(float(hum), 2)
            return None
        except RuntimeError:
            # Catch standard DHT11 timing / checksum errors to prevent crashes
            return None
        except Exception as err:
            print(f"Unexpected DHT sensor read error: {err}")
            return None

    def exit(self):
        """Release the GPIO pin back to the OS to avoid 'Unable to set line' errors."""
        if hasattr(self, "dev") and self.dev is not None:
            try:
                self.dev.exit()
                print(f"Released GPIO pin for '{self.pin_name}'.")
            except Exception as err:
                print(f"Error releasing GPIO pin: {err}")

    def close(self):
        self.exit()
