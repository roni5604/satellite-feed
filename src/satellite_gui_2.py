import sys
import os
import signal
import time
import requests

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStatusBar,
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy
)
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import GLViewWidget, MeshData, GLMeshItem, GLGridItem
import numpy as np
from stl import mesh as stl_mesh
import pyqtgraph as pg

# API endpoint and polling interval (milliseconds)
ANGLES_URL    = "http://127.0.0.1:5003/angles"
POLL_INTERVAL = 5000  # 5 seconds

# Fixed satellite altitude above Earth
ALTITUDE = 500.0

def rotation_matrix_x(deg: float) -> np.ndarray:
    a = np.deg2rad(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0],
                     [0, c, -s],
                     [0, s,  c]])

def handle_sigint(signum, frame):
    print("\n🔆 Goodbye! 🔆")
    sys.exit(0)

class SatelliteViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Satellite Attitude Viewer")
        signal.signal(signal.SIGINT, handle_sigint)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        # 3D view setup
        self.view = GLViewWidget()
        self.view.setBackgroundColor('k')
        self.view.setCameraPosition(distance=350.0, elevation=10.0, azimuth=-810.0)
        self.view.opts['center'] = pg.Vector(0, 0, ALTITUDE)

        # Ground grid
        grid = GLGridItem()
        grid.scale(100, 100, 1)
        self.view.addItem(grid)

        # Load STL mesh
        project_root = os.path.dirname(os.path.dirname(__file__))
        stl_path = os.path.join(project_root, "static", "pod_box.stl")
        mesh = stl_mesh.Mesh.from_file(stl_path)
        verts = mesh.vectors.reshape(-1, 3)
        verts -= verts.mean(axis=0)
        faces = np.arange(len(verts)).reshape(-1, 3)

        # Rotate model upright
        verts = verts @ rotation_matrix_x(90).T

        # Compute center_z so model sits at ALTITUDE
        zmin, zmax = verts[:, 2].min(), verts[:, 2].max()
        height = zmax - zmin
        self.center_z = ALTITUDE + height / 2

        # Create and add mesh item
        md = MeshData(vertexes=verts, faces=faces)
        self.sat = GLMeshItem(meshdata=md, smooth=True,
                              color=(0.7, 0.7, 0.7, 1),
                              shader='shaded', drawEdges=True)
        self.view.addItem(self.sat)

        # Side panel for heading/tilt
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setAlignment(Qt.AlignTop)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setFixedWidth(150)

        heading_label = QLabel("Heading:")
        heading_label.setAlignment(Qt.AlignCenter)
        heading_label.setStyleSheet("font: 14px;")
        self.heading_value = QLabel("– °")
        self.heading_value.setAlignment(Qt.AlignCenter)
        self.heading_value.setStyleSheet("font: 18px; font-weight: bold;")

        tilt_label = QLabel("Tilt:")
        tilt_label.setAlignment(Qt.AlignCenter)
        tilt_label.setStyleSheet("font: 14px;")
        self.tilt_value = QLabel("– °")
        self.tilt_value.setAlignment(Qt.AlignCenter)
        self.tilt_value.setStyleSheet("font: 18px; font-weight: bold;")

        panel_layout.addWidget(heading_label)
        panel_layout.addWidget(self.heading_value)
        panel_layout.addSpacing(20)
        panel_layout.addWidget(tilt_label)
        panel_layout.addWidget(self.tilt_value)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.addWidget(self.view, 1)
        layout.addWidget(panel)
        self.setCentralWidget(container)

        # Timers
        cam_timer = QTimer(self)
        cam_timer.timeout.connect(self._update_status)
        cam_timer.start(100)

        self.angle_timer = QTimer(self)
        self.angle_timer.timeout.connect(self._poll_and_update_angles)
        self.angle_timer.start(POLL_INTERVAL)

        # Initial orientation
        self._apply_attitude(el=0, az=0)

    def _poll_and_update_angles(self):
        try:
            r = requests.get(ANGLES_URL, timeout=2.0)
            r.raise_for_status()
            data = r.json()
            heading = float(data.get("heading", 0.0))
            tilt    = float(data.get("tilt",    0.0))
            print(f"[{time.strftime('%H:%M:%S')}] Heading={heading:.2f}°, Tilt={tilt:.2f}°")
            self.heading_value.setText(f"{heading:.2f} °")
            self.tilt_value.setText(f"{tilt:.2f} °")
            self._apply_attitude(el=tilt, az=heading)
        except Exception as e:
            print(f"[ERROR] fetching angles: {e}")

    def _apply_attitude(self, el: float, az: float):
        # Base alignment: stand upright along Z
        self.sat.resetTransform()
        self.sat.rotate(90, 0, 1, 0)

        # Apply yaw (heading) and pitch (tilt)
        self.sat.rotate(az,   0, 0, 1)
        self.sat.rotate(-el,  1, 0, 0)
        self.sat.translate(0, 0, self.center_z)

    def _update_status(self):
        opts = self.view.opts
        msg = f"Cam: d={opts['distance']:.1f}, el={opts['elevation']:.1f}°, az={opts['azimuth']:.1f}°"
        self.status.showMessage(msg)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SatelliteViewer()
    window.resize(1100, 600)
    window.show()
    sys.exit(app.exec())



