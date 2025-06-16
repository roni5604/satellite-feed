# shared_state.py

import threading

# Shared data with thread-safe access
class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.focus_mod = True
        self.heading_rate = 0.0
        self.tilt_rate = 0.0

    def get_values(self):
        with self.lock:
            return self.focus_mod, self.heading_rate, self.tilt_rate

    def set_values(self, focus=None, heading_rate=None, tilt_rate=None, energy_use=None):
        with self.lock:
            if focus is not None:
                self.focus_mod = focus
            if heading_rate is not None:
                self.heading_rate = heading_rate
            if tilt_rate is not None:
                self.tilt_rate = tilt_rate

# Singleton instance
state = SharedState()
