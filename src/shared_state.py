# shared_state.py
import threading

# Shared data with thread-safe access
class SharedState:
   def __init__(self):
       self.lock = threading.Lock()
       self.focus_mod = False
       self.heading_rate = 0.0
       self.tilt_rate = 0.0
       self.heading = 0.0
       self.tilt = 100.0


   def get_values(self):
       with self.lock:
           return self.focus_mod, self.heading_rate, self.tilt_rate


   def get_angles(self):
       print("Fetching angles from shared state")
       with self.lock:
           return self.heading, self.tilt

   def set_values(self, focus_mod=None, heading_rate=None, tilt_rate=None, energy_use=None, heading=None, tilt=None):
       with self.lock:
           if focus_mod is not None:
               self.focus_mod = focus_mod
           if heading_rate is not None:
               self.heading_rate = heading_rate
           if tilt_rate is not None:
               self.tilt_rate = tilt_rate
           if energy_use is not None:
                self.energy_use = energy_use
           if heading is not None:
                self.heading = heading
           if tilt is not None:
                self.tilt = tilt


# Singleton instance
state = SharedState()

# Optional: external access
def get_angles():
   return state.get_angles()