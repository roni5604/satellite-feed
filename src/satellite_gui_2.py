import sys
import signal
import time
import requests


from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStatusBar,
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy
)
from pyqtgraph.opengl import (
    GLViewWidget, GLGridItem,
    GLLinePlotItem, GLScatterPlotItem
)
import numpy as np
import pyqtgraph as pg


# ----------------------------------------------------------------------------
# Configuration constants
# ----------------------------------------------------------------------------
ANGLES_URL    = "http://127.0.0.1:5003/angles"
POLL_INTERVAL = 500      # ms
ALTITUDE      = 500.0    # fixed satellite altitude (m)


def handle_sigint(signum, frame):
    """Handle Ctrl+C gracefully by exiting the application."""
    print("\n🔆 Goodbye! 🔆")
    sys.exit(0)


class SatelliteViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Satellite Attitude & Target Viewer")
        signal.signal(signal.SIGINT, handle_sigint)


        # status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)


        # 3D view
        self.view = GLViewWidget()
        self.view.setBackgroundColor('k')
        self.view.setCameraPosition(distance=800.0, elevation=20.0, azimuth=45.0)
        self.view.opts['center'] = pg.Vector(0, 0, ALTITUDE)


        # ground grid
        grid = GLGridItem()
        grid.scale(100, 100, 1)
        self.view.addItem(grid)


        # קו ורטיקלי (ציר Z) מאפס עד ALTITUDE
        pts_vert = np.array([[0,0,0], [0,0,ALTITUDE]])
        vert_line = GLLinePlotItem(pos=pts_vert, color=(0.5,0.5,0.5,1), width=2, antialias=True)
        self.view.addItem(vert_line)


        # visualization parameters
        self.axis_len = 100.0
        self.center_z  = ALTITUDE


        # heading axis (ירוק)
        self.heading_line = GLLinePlotItem(width=3, antialias=True, color=(0,1,0,1))
        self.view.addItem(self.heading_line)
        # tilt axis (כחול)
        self.tilt_line = GLLinePlotItem(width=3, antialias=True, color=(0,0,1,1))
        self.view.addItem(self.tilt_line)
        # laser beam (אדום)
        self.view_line = GLLinePlotItem(width=4, antialias=True, color=(1,0,0,1))
        self.view.addItem(self.view_line)
        # target marker
        self.target_point = GLScatterPlotItem(pos=np.zeros((1,3)), size=10, color=(1,0,0,1))
        self.view.addItem(self.target_point)


        # side panel
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setAlignment(Qt.AlignTop)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setFixedWidth(150)


        heading_label = QLabel("Heading:")
        heading_label.setAlignment(Qt.AlignCenter)
        heading_label.setStyleSheet("font:14px;")
        self.heading_value = QLabel("– °")
        self.heading_value.setAlignment(Qt.AlignCenter)
        self.heading_value.setStyleSheet("font:18px; font-weight:bold;")


        tilt_label = QLabel("Tilt:")
        tilt_label.setAlignment(Qt.AlignCenter)
        tilt_label.setStyleSheet("font:14px;")
        self.tilt_value = QLabel("– °")
        self.tilt_value.setAlignment(Qt.AlignCenter)
        self.tilt_value.setStyleSheet("font:18px; font-weight:bold;")


        panel_layout.addWidget(heading_label)
        panel_layout.addWidget(self.heading_value)
        panel_layout.addSpacing(20)
        panel_layout.addWidget(tilt_label)
        panel_layout.addWidget(self.tilt_value)


        # main layout
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.addWidget(self.view, 1)
        layout.addWidget(panel)
        self.setCentralWidget(container)


        # timers
        cam_timer = QTimer(self)
        cam_timer.timeout.connect(self._update_status)
        cam_timer.start(100)


        self.angle_timer = QTimer(self)
        self.angle_timer.timeout.connect(self._poll_and_update_angles)
        self.angle_timer.start(POLL_INTERVAL)


        # init
        self._apply_attitude(el=0.0, az=0.0)


    def _poll_and_update_angles(self):
        try:
            resp = requests.get(ANGLES_URL, timeout=2.0)
            resp.raise_for_status()
            data = resp.json()
            heading = float(data.get("heading", 0.0))
            tilt    = float(data.get("tilt",    0.0))
            tilt = max(0.0, min(tilt, 90.0))


            self.heading_value.setText(f"{heading:.2f} °")
            self.tilt_value.setText(f"{tilt:.2f} °")


            print(f"[{time.strftime('%H:%M:%S')}] Heading={heading:.2f}°, Tilt={tilt:.2f}°")
            self._apply_attitude(el=tilt, az=heading)


        except Exception as e:
            print(f"[ERROR] fetching angles: {e}")


    def _apply_attitude(self, el: float, az: float):
        ar = np.deg2rad(az)
        er = np.deg2rad(el)


        # heading vector
        d_h = np.array([np.sin(ar), np.cos(ar), 0.0])
        # tilt vector
        x = np.sin(er) * np.sin(ar)
        y = np.sin(er) * np.cos(ar)
        z = -np.cos(er)
        d_t = np.array([x, y, z])


        origin = np.array([0.0, 0.0, self.center_z])


        # draw heading
        pts_h = np.vstack([origin, origin + d_h * self.axis_len])
        self.heading_line.setData(pos=pts_h)


        # draw tilt
        pts_t = np.vstack([origin, origin + d_t * self.axis_len])
        self.tilt_line.setData(pos=pts_t)


        # intersection with ground
        if d_t[2] != 0:
            t_ground = -origin[2] / d_t[2]
            ground_pt = origin + d_t * t_ground
            pts_v = np.vstack([origin, ground_pt])
            self.view_line.setData(pos=pts_v)
            self.target_point.setData(pos=np.array([ground_pt]))
        else:
            self.view_line.setData(pos=np.empty((0,3)))
            self.target_point.setData(pos=np.empty((0,3)))


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





