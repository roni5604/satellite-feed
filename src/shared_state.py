# shared_state.py

import threading

# Shared data with thread-safe access
class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.focus_mod = False
        self.heading_rate = 0.0
        self.tilt_rate = 0.0

    def get_values(self):
        with self.lock:
            return self.focus_mod, self.heading_rate, self.tilt_rate

    def set_values(self, focus_mod=None, heading_rate=None, tilt_rate=None):
        with self.lock:
            if focus_mod is not None:
                print(f"[SharedState] focus_mod updated to: {focus_mod:.4f} deg/s")
                self.focus_mod = focus_mod
            if heading_rate is not None:
                print(f"[SharedState] heading_rate updated to: {heading_rate:.4f} deg/s")
                self.heading_rate = heading_rate
            if tilt_rate is not None:
                print(f"[SharedState] tilt_rate updated to: {tilt_rate:.4f} deg/s")
                self.tilt_rate = tilt_rate


# Singleton instance
state = SharedState()
