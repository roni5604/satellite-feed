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


    def calculate_energy_use(self, heading, tilt):
        return heading * 0.4 + tilt * 0.6 ######################### TODO: Implement energy consumption model

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
        self.heading_label.config(text=f"Heading Rate: {heading_rate:.2f}")
        self.heading_bar["value"] = min(heading_rate, 100.0)

        # Update tilt
        self.tilt_label.config(text=f"Tilt Rate: {tilt_rate:.2f}")
        self.tilt_bar["value"] = min(tilt_rate, 100.0)

        # Energy
        energy_use = self.calculate_energy_use(heading_rate, tilt_rate)
        self.energy_label.config(text=f"Energy Use: {energy_use:.2f}")
        self.energy_bar["value"] = min(energy_use, 100.0)

        self.root.after(100, self.update_gui)

if __name__ == "__main__":
    root = tk.Tk()
    gui = SimulationGUI(root)
    root.mainloop()
