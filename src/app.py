import os
import threading
import time
import logging
import signal
import sys
import math
import requests
from PySide6.QtWidgets import QApplication
from skyfield.api import load, EarthSatellite, wgs84
from flask import Flask, Response, send_file
import random
import time
from flask import request, jsonify
from shared_state import state
import tkinter as tk
from simulation_gui import SimulationGUI
from satellite_gui import SatelliteViewer

start_time = time.time()
orbit_angular_speeds = []
focus_angular_speeds = []

prev_heading = None
prev_tilt = None
prev_time = None

app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# ============================================
#  Constants / Settings:
# ============================================
TLE_URL = "https://celestrak.com/NORAD/elements/stations.txt"
UPDATE_INTERVAL_S = 5  # Fetch ISS position every 5 seconds

# HOW MUCH LOWER (in meters) the camera should be compared to the exact slant distance:
ALT_OFFSET_M = 50000.0  # 50 km lower than the precise slant‐range

# Icon color for the fixed ground target (AABBGGRR); here: fully opaque red
TARGET_COLOR = "ff0000ff"
TARGET_NAME_PREFIX = "Orbit-Target"  # Name prefix for KML placemarks
PREDICTION_DURATION_MIN = 90  # ≈ one ISS orbit
TARGET_INTERVAL_S = 60  # add a target point every 60 s

# Store ISS positions over time: list of tuples (lat_deg, lon_deg, alt_km)
positions_history: list[tuple[float, float, float]] = []  # (lat,lon,alt_km)
target_points: list[tuple[float, float]] = []  # (lat,lon) ground pts

# TLE lines for the ISS (populated once at startup)
tle_line1 = tle_line2 = None


def fetch_iss_tle():
    """
    Fetch the ISS TLE (Two-Line Element set) from Celestrak.
    Returns a tuple: (line1, line2) of the TLE for ISS (ZARYA).
    """
    r = requests.get(TLE_URL, timeout=10)
    lines = r.text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("ISS (ZARYA)"):
            return lines[i + 1].strip(), lines[i + 2].strip()
    raise RuntimeError("ISS TLE not found in the fetched data.")


def get_sat_position(line1, line2, when=None):
    """
    Compute the ISS's geodetic position using Skyfield.
    - line1, line2: the TLE lines for ISS.
    - when: a Skyfield Time object (if None, we use ts.now()).
    Returns (latitude_deg, longitude_deg, altitude_km).
    """
    ts = load.timescale()
    sat = EarthSatellite(line1, line2, name="ISS", ts=ts)

    if when is None:
        t = ts.now()
    else:
        t = when

    geo = sat.at(t)
    lat, lon = wgs84.latlon_of(geo)
    alt_km = wgs84.height_of(geo).km
    return float(lat.degrees), float(lon.degrees), float(alt_km)


def haversine_km(lat1, lon1, lat2, lon2):
    """
    Great‐circle distance (in kilometers) between (lat1, lon1) and (lat2, lon2).
    """
    R = 6371.0  # Earth radius in kilometers
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = φ2 - φ1
    Δλ = math.radians(lon2 - lon1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """
    Initial bearing in degrees from (lat1, lon1) → (lat2, lon2).
    Formula: θ = atan2( sin(Δλ)⋅cos(φ₂), cos(φ₁)⋅sin(φ₂) − sin(φ₁)⋅cos(φ₂)⋅cos(Δλ) ).
    Returns a value in [0, 360).
    """
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    x = math.sin(Δλ) * math.cos(φ2)
    y = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(Δλ)
    θ = math.atan2(x, y)
    return (math.degrees(θ) + 360) % 360


def precompute_targets(window_minutes=PREDICTION_DURATION_MIN):
    """
    Fill `target_points` with ground-projected ISS positions every
    TARGET_INTERVAL_S seconds for the next `window_minutes`.
    Run once at start so the map is populated from the first request.
    """
    global target_points, tle_line1, tle_line2
    ts = load.timescale()
    sat = EarthSatellite(tle_line1, tle_line2, "ISS", ts)

    now = ts.now()
    steps = int((window_minutes * 60) / TARGET_INTERVAL_S)
    target_points.clear()  # start fresh
    for i in range(steps):
        t = now + (i * TARGET_INTERVAL_S) / 86400.0  # Skyfield uses days
        geo = sat.at(t)
        lat, lon = wgs84.latlon_of(geo)
        target_points.append((float(lat.degrees), float(lon.degrees)))

    print(f"[Tracker] Pre-computed {len(target_points)} target points "
          f"({window_minutes} min, {TARGET_INTERVAL_S}s spacing).")


def precompute_shifted_targets(window_minutes=PREDICTION_DURATION_MIN,
                               max_shift_km=0.0,  # X km: max deviation
                               shift_prob=0.0):  # y: chance [0.0–1.0]
    """
    Precompute ground-projected targets.
    Optionally shift some laterally (left/right) up to `max_shift_km` with probability `shift_prob`.
    """
    global target_points, tle_line1, tle_line2
    ts = load.timescale()
    sat = EarthSatellite(tle_line1, tle_line2, "ISS", ts)

    now = ts.now()
    steps = int((window_minutes * 60) / TARGET_INTERVAL_S)
    target_points.clear()

    prev_lat = prev_lon = None  # used to approximate satellite bearing

    for i in range(steps):
        t = now + (i * TARGET_INTERVAL_S) / 86400.0
        geo = sat.at(t)
        lat, lon = wgs84.latlon_of(geo)
        lat = float(lat.degrees)
        lon = float(lon.degrees)

        # Determine bearing from previous point (if available)
        if prev_lat is not None and prev_lon is not None:
            bearing = bearing_deg(prev_lat, prev_lon, lat, lon)

            if random.random() < shift_prob and max_shift_km > 0.0:
                # Choose left (−90°) or right (+90°)
                direction = random.choice([-90, 90])
                shift_angle = math.radians((bearing + direction) % 360)

                # Shift by up to X km
                shift_km = random.uniform(0, max_shift_km)
                R = 6371.0  # Earth radius in km
                d_lat = (shift_km / R) * math.cos(shift_angle)
                d_lon = (shift_km / R) * math.sin(shift_angle) / math.cos(math.radians(lat))

                if random.random() < 0.5:
                    # Shift left
                    lat -= math.degrees(d_lat)
                    lon -= math.degrees(d_lon)
                else:
                    lat += math.degrees(d_lat)
                    lon += math.degrees(d_lon)

        target_points.append((lat, lon))
        prev_lat, prev_lon = lat, lon

    print(f"[Tracker] Pre-computed {len(target_points)} target points "
          f"({window_minutes} min, {TARGET_INTERVAL_S}s spacing).")


def satellite_updater():
    """
    Background thread to:
      1. Fetch the ISS TLE once.
      2. Compute the “lead-track” ground target 30 seconds in the future.
      3. Every UPDATE_INTERVAL_S seconds, compute the current ISS position,
         append to positions_history, then compute and print the LookAt parameters:
         - heading (azimuth toward the fixed target),
         - tilt (camera tilt so it points at the ISS),
         - adjusted_range_m (slant range minus ALT_OFFSET_M).
    """
    global tle_line1, tle_line2
    if tle_line1 is None:  # first run only
        print("[Tracker] Fetching ISS TLE…")
        tle_line1, tle_line2 = fetch_iss_tle()
        print("[Tracker] TLE acquired.")

    while True:
        # 3) Compute current ISS position (lat, lon, alt_km):
        lat, lon, alt_km = get_sat_position(tle_line1, tle_line2)
        positions_history.append((lat, lon, alt_km))
        time.sleep(UPDATE_INTERVAL_S)


def calculate_3d_distance_km(sat_lat, sat_lon, sat_alt_km, tgt_lat, tgt_lon, tgt_alt_km):
    """
    Calculate 3D distance (km) between satellite and ground target.
    """
    R_earth = 6371.0

    def to_cartesian(lat, lon, alt, R_base):
        radius = R_base + alt
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        x = radius * math.cos(lat_rad) * math.cos(lon_rad)
        y = radius * math.cos(lat_rad) * math.sin(lon_rad)
        z = radius * math.sin(lat_rad)
        return x, y, z

    x1, y1, z1 = to_cartesian(sat_lat, sat_lon, sat_alt_km, R_earth)
    x2, y2, z2 = to_cartesian(tgt_lat, tgt_lon, tgt_alt_km, R_earth)

    distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)
    return distance


@app.route("/state")
def get_state():
    focus, heading, tilt = state.get_values()
    return jsonify({
        "focus_mod": focus,
        "heading_rate": heading,
        "tilt_rate": tilt
    })

@app.route("/set_state", methods=["POST"])
def set_state():
    data = request.json
    state.set_values(
        focus_mod=data.get("focus_mod"),
        heading_rate=data.get("heading_rate"),
        tilt_rate=data.get("tilt_rate")
    )
    return jsonify({"status": "ok"})


@app.route("/orbit.kml")
def stream_kml_orbit_only():
    """
    * Simple orbit tracking: Earth-centered view
    * KML includes ISS path as white LineString
    * LookAt follows satellite, looking straight down
    * Computes and prints heading and tilt rate (deg/s)
    """
    if len(positions_history) < 2:
        return Response("", status=204)

    # Satellite current position
    sat_lat, sat_lon, sat_alt_km = positions_history[-1]
    alt_m = sat_alt_km * 1000

    global prev_time, prev_lat, prev_lon

    # Measure angular changes for logging
    now = time.time()
    if prev_time is not None:
        delta_t = now - prev_time
        delta_heading = abs(sat_lon - prev_lon)
        delta_tilt = abs(sat_lat - prev_lat)

        heading_rate = delta_heading / delta_t
        tilt_rate = delta_tilt / delta_t

        state.set_values(heading=0.0,
                         tilt=0.0,
                         heading_rate=heading_rate,
                         tilt_rate=tilt_rate)

        print(f"[ΔAngles] ORBIT mode – Heading rate: {heading_rate:.4f} deg/s, Tilt rate: {tilt_rate:.4f} deg/s")

    prev_time = now
    prev_lat = sat_lat
    prev_lon = sat_lon

    # LookAt tag (camera looks straight down on satellite)
    lookat = f"""
    <LookAt>
      <longitude>{sat_lon:.6f}</longitude>
      <latitude>{sat_lat:.6f}</latitude>
      <altitude>0</altitude>
      <heading>0</heading>
      <tilt>0</tilt>
      <range>{alt_m:.1f}</range>
      <altitudeMode>absolute</altitudeMode>
    </LookAt>"""

    coords = " ".join(f"{lo:.6f},{la:.6f},{al * 1000:.1f}"
                      for la, lo, al in positions_history)

    path_style = """
    <Style id="pathStyle">
      <LineStyle>
        <color>ffffffff</color>
        <width>2</width>
      </LineStyle>
    </Style>"""

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>ISS Orbit Path</name>
    {lookat}
    {path_style}
    <Placemark>
      <name>ISS Path</name>
      <styleUrl>#pathStyle</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>
          {coords}
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""

    return Response(kml, mimetype="application/vnd.google-earth-kml+xml")


@app.route("/live.kml")
def stream_kml():
    """
    * Camera viewpoint = current ISS position
    * Camera looks at the *nearest* target point (if any)
    * Every target point is drawn as a Placemark
    * The ISS path is drawn as a single white LineString
    * Range is computed via calculate_3d_distance_km + 3000m
    """
    # Safety: nothing to show yet
    if not positions_history or not target_points:
        return Response("", status=204)

    # ------------------------------------------------------------------
    # 1)  Grab current ISS position
    sat_lat, sat_lon, sat_alt_km = positions_history[-1]

    # 2)  Pick nearest target (horizontal distance only)
    tgt_lat, tgt_lon = min(
        target_points,
        key=lambda t: haversine_km(sat_lat, sat_lon, t[0], t[1])
    )
    # Print nearest-target info
    dist_km = haversine_km(sat_lat, sat_lon, tgt_lat, tgt_lon)
    print(f"[Tracker] Closest target: lat={tgt_lat:.6f}, lon={tgt_lon:.6f}, Air Distance: {dist_km:.1f} km")

    # 3)  Compute 3D range - real distance from satelitte to target
    real_dist = calculate_3d_distance_km(sat_lat, sat_lon, sat_alt_km, tgt_lat, tgt_lon, 0)
    lookat_range_m = real_dist * 1000

    # 4)  Geometry from ISS → target
    heading = bearing_deg(sat_lat, sat_lon, tgt_lat, tgt_lon)
    elev_deg = math.degrees(math.atan2(sat_alt_km, dist_km)) if dist_km else 90.0
    tilt = max(0.0, min(90.0, 90.0 - elev_deg))

    # 5) Compute angular speed and store it
    lat1, lon1, _ = positions_history[-2] if len(positions_history) >= 2 else (sat_lat, sat_lon, sat_alt_km)
    angle = haversine_km(lat1, lon1, sat_lat, sat_lon) / 6371.0  # radians
    angular_speed_deg = math.degrees(angle) / UPDATE_INTERVAL_S
    focus_angular_speeds.append(angular_speed_deg)

    global prev_heading, prev_tilt, prev_time

    now = time.time()

    if prev_heading is not None and prev_tilt is not None and prev_time is not None:
        delta_t = now - prev_time
        delta_heading = abs(heading - prev_heading)
        delta_tilt = abs(tilt - prev_tilt)

        heading_rate = delta_heading / delta_t
        tilt_rate = delta_tilt / delta_t
        state.set_values(heading=heading,
                         tilt=tilt,
                         heading_rate=heading_rate,
                         tilt_rate=tilt_rate)
        print(f"[ΔAngles] FOCUS mode – Heading rate: {heading_rate:.4f} deg/s, Tilt rate: {tilt_rate:.4f} deg/s")

    prev_heading = heading
    prev_tilt = tilt
    prev_time = now

    # ------------------------------------------------------------------
    # 6)  Assemble KML: LookAt + Styles
    lookat = f"""
    <LookAt>
      <longitude>{tgt_lon:.6f}</longitude>
      <latitude>{tgt_lat:.6f}</latitude>
      <altitude>0</altitude>
      <range>{lookat_range_m:.1f}</range>
      <tilt>{tilt:.1f}</tilt>
      <heading>{heading:.1f}</heading>
      <altitudeMode>absolute</altitudeMode>
    </LookAt>"""

    # Style for the ground targets (red circle)
    style = f"""
    <Style id="targetStyle">
      <IconStyle>
        <color>{TARGET_COLOR}</color>
        <scale>1.3</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>
        </Icon>
      </IconStyle>
    </Style>"""

    # Style for the ISS path line (white, width=2)
    path_style = """
    <Style id="pathStyle">
      <LineStyle>
        <color>ffffffff</color>
        <width>2</width>
      </LineStyle>
    </Style>"""

    # ---------- Placemarks ----------
    placemarks = ""
    # a) Ground-projected target points
    for i, (la, lo) in enumerate(target_points, start=1):
        placemarks += f"""
    <Placemark>
      <name>{TARGET_NAME_PREFIX} {i}</name>
      <styleUrl>#targetStyle</styleUrl>
      <Point>
        <coordinates>{lo:.6f},{la:.6f},0</coordinates>
      </Point>
    </Placemark>"""

    # b) Single LineString showing the ISS path
    coords = " ".join(f"{lo:.6f},{la:.6f},{al * 1000:.1f}"
                      for la, lo, al in positions_history)
    placemarks += f"""
    <Placemark>
      <name>ISS Path</name>
      <styleUrl>#pathStyle</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>
          {coords}
        </coordinates>
      </LineString>
    </Placemark>"""

    # Assemble the full KML
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Real-Time ISS Tracker – Orbit Targets</name>
    {style}
    {path_style}
    {lookat}
    {placemarks}
  </Document>
</kml>"""

    return Response(kml, mimetype="application/vnd.google-earth-kml+xml")


@app.route("/dynamic.kml")
def dynamic_kml():
    if state.get_values()[0]:  # focus_mod is True
        return stream_kml()
    else:
        return stream_kml_orbit_only()


def start_simulation_gui():
    root = tk.Tk()
    gui = SimulationGUI(root)
    root.mainloop()

# def start_satellite_gui():
#     """
#     Entry-point that can be imported and called
#     from another script (`app.exec()` blocks).
#     """
#     app = QApplication.instance() or QApplication(sys.argv)
#     win = SatelliteViewer()
#     win.resize(1100, 600)
#     win.show()
#     sys.exit(app.exec())
#

def shutdown_handler(sig, frame):
    """
    Graceful shutdown handler (e.g., on Ctrl+C).
    """
    print("\n[Tracker] Exiting gracefully. Goodbye! 👋")
    sys.exit(0)

@app.route("/angles")
def angles():
   """
   Returns the last computed heading & tilt as JSON,
   so that satellite_gui.py can poll them.
   """
   # state.get_angles() should return (heading, tilt)
   h, t = state.get_angles()
   print(f"[Tracker] Angles: Heading={h:.2f}°, Tilt={t:.2f}°")
   return jsonify({
       "heading": round(h, 2),
       "tilt":    round(t, 2),
   })


if __name__ == "__main__":
    # Start the GUI in a separate thread
    threading.Thread(target=start_simulation_gui, daemon=True).start()

    # Catch SIGINT (Ctrl+C) to exit cleanly
    tle_line1, tle_line2 = fetch_iss_tle()

    # Fill `target_points` for the next 90 min (or whatever you chose)
    precompute_shifted_targets(max_shift_km=200.0, shift_prob=0.9)  # Example with shifting

    signal.signal(signal.SIGINT, shutdown_handler)
    threading.Thread(target=satellite_updater, daemon=True).start()
    print("[Tracker] Flask server on port 5003 …")
    app.run(host="0.0.0.0", port=5003)

"""
    ToDo:
    - add more camera targets                                       V
    - make the target shift off course by up to X kilometers        V
    - make the camara look at the closest target                    V

    - add info gui with:
     speed, angle, camera angle, distance to the closest target and the secound closest (with directions)

"""
