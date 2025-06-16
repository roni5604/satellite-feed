# simulation_gui.py
import tkinter as tk
from tkinter import ttk
from shared_state import state  # <- shared state instance

MAX_VALUE = 100.0

class SimulationGUI:
    def __init__(self, root):
        self.root = root
        root.title("Simulation GUI")
        root.geometry("400x300")

        self.focus_button = ttk.Button(root, text="Start Focus Simulation", command=self.toggle_focus)
        self.focus_button.pack(pady=10)

        self.heading_label = ttk.Label(root, text="")
        self.heading_label.pack()
        self.heading_bar = ttk.Progressbar(root, maximum=MAX_VALUE, length=300)
        self.heading_bar.pack(pady=5)

        self.tilt_label = ttk.Label(root, text="")
        self.tilt_label.pack()
        self.tilt_bar = ttk.Progressbar(root, maximum=MAX_VALUE, length=300)
        self.tilt_bar.pack(pady=5)

        self.energy_label = ttk.Label(root, text="")
        self.energy_label.pack()
        self.energy_bar = ttk.Progressbar(root, maximum=MAX_VALUE, length=300)
        self.energy_bar.pack(pady=5)

        self.update_gui()

    def toggle_focus(self):
        current_focus, _, _, _ = state.get_values()
        state.set_values(focus=not current_focus)
        self.focus_button.config(
            text="Stop Focus Simulation" if not current_focus else "Start Focus Simulation"
        )

    def update_gui(self):
        focus, heading, tilt, energy = state.get_values()

        self.heading_label.config(text=f"Heading Rate: {heading:.1f}")
        self.heading_bar['value'] = heading

        self.tilt_label.config(text=f"Tilt Rate: {tilt:.1f}")
        self.tilt_bar['value'] = tilt

        self.energy_label.config(text=f"Energy Use: {energy:.1f}")
        self.energy_bar['value'] = energy

        self.focus_button.config(
            text="Stop Focus Simulation" if focus else "Start Focus Simulation"
        )

        self.root.after(100, self.update_gui)
