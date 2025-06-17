# simulation_gui.py
import requests
import tkinter as tk
from tkinter import ttk
from shared_state import state

class SimulationGUI:
    def __init__(self, root):
        self.root = root
        root.title("Simulation GUI")
        root.geometry("400x350")

        # Focus button
        self.focus_button = ttk.Button(root, text="Start Focus Simulation", command=self.toggle_focus)
        self.focus_button.pack(pady=10)

        # Heading Rate display
        self.heading_label = ttk.Label(root, text="Heading Rate: 0.0")
        self.heading_label.pack()
        self.heading_bar = ttk.Progressbar(root, length=300, maximum=100.0)
        self.heading_bar.pack(pady=5)

        # Tilt Rate display
        self.tilt_label = ttk.Label(root, text="Tilt Rate: 0.0")
        self.tilt_label.pack()
        self.tilt_bar = ttk.Progressbar(root, length=300, maximum=100.0)
        self.tilt_bar.pack(pady=5)

        # Energy Use display (calculated locally)
        self.energy_label = ttk.Label(root, text="Energy Use: 0.0")
        self.energy_label.pack()
        self.energy_bar = ttk.Progressbar(root, length=300, maximum=100.0)
        self.energy_bar.pack(pady=5)

        self.update_gui()

    def toggle_focus(self):
        current_focus, _, _ = state.get_values()
        new_focus = not current_focus
        try:
            requests.post("http://localhost:5003/set_state", json={"focus_mod": new_focus})
        except Exception as e:
            print("Failed to update focus_mod on server:", e)

    def update_energy_use(self):
        """Compute instantaneous power draw and store it in shared_state."""
        focus, h_rate, t_rate = state.get_values()

        P_idle = 5.0                      # idle power consumption in watts
        k_h, k_t = 0.03, 0.04             # the power coefficients for heading and tilt rates
        P_focus = 10.0 if focus else 0.0  # when focus mode is active the satellite consumes more power for calculations

        energy = P_idle + k_h * h_rate ** 2 + k_t * t_rate ** 2 + P_focus
        # state.set_values(energy_use=energy)
        return energy

    def update_gui(self):
        try:
            res = requests.get("http://localhost:5003/state")
            data = res.json()
            focus_mod = data["focus_mod"]
            heading_rate = data["heading_rate"]
            tilt_rate = data["tilt_rate"]
        except Exception as e:
            print("Failed to fetch state:", e)
            focus_mod, heading_rate, tilt_rate = False, 0.0, 0.0

        # Update heading
        self.heading_label.config(text=f"Heading Rate (deg/s): {heading_rate:.2f}")
        self.heading_bar["value"] = min(heading_rate, 80.0)

        # Update tilt
        self.tilt_label.config(text=f"Tilt Rate (deg/s): {tilt_rate:.2f}")
        self.tilt_bar["value"] = min(tilt_rate, 80.0)

        # Energy
        energy_use = self.update_energy_use()
        self.energy_label.config(text=f"Energy Use (W): {energy_use:.2f}")
        self.energy_bar["value"] = min(energy_use, 100.0)

        self.root.after(100, self.update_gui)

if __name__ == "__main__":
    root = tk.Tk()
    gui = SimulationGUI(root)
    root.mainloop()