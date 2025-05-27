#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import time
import logging
import signal
import sys
import math
import requests
from skyfield.api import load, EarthSatellite, wgs84
from flask import Flask, Response

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# ========================
#  Configuration
# ========================
# Try using the "www" prefix to avoid 403
TLE_URLS = [
    "https://www.celestrak.com/NORAD/elements/stations.txt",
    "http://www.celestrak.com/NORAD/elements/stations.txt"
]
UPDATE_INTERVAL_S = 5  # seconds

# Target Point settings
TARGET_LAT = 31.8
TARGET_LON = 35.2
TARGET_NAME = "Target Site"
TARGET_COLOR = "ff0000ff"  # AABBGGRR

# Camera range
LOOKAT_RANGE_M = 700_000

# History of ISS positions [(lat, lon, alt_km), ...]
positions_history = []
tle_line1 = tle_line2 = None


def fetch_iss_tle():
    """Attempt to fetch ISS TLE from multiple URLs until success."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ISS-Tracker/1.0)"}
    for url in TLE_URLS:
        try:
            resp = requests.get(url, timeout=10, headers=headers)
            resp.raise_for_status()
            lines = resp.text.splitlines()
            for i, line in enumerate(lines):
                if line.strip().startswith("ISS (ZARYA)"):
                    return lines[i+1].strip(), lines[i+2].strip()
        except Exception as e:
            print(f"[Tracker] TLE fetch attempt failed for {url}: {e}")
    raise RuntimeError("ISS TLE not found in any source")


def get_sat_position(line1, line2):
    ts = load.timescale()
    sat = EarthSatellite(line1, line2, name="ISS", ts=ts)
    t = ts.now()
    geo = sat.at(t)
    lat, lon = wgs84.latlon_of(geo)
    alt_km = wgs84.height_of(geo).km
    return float(lat.degrees), float(lon.degrees), float(alt_km)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def bearing_deg(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlambda)
    theta = math.atan2(x, y)
    return (math.degrees(theta) + 360) % 360


def satellite_updater():
    global tle_line1, tle_line2
    # Try fetching TLE until success
    while tle_line1 is None:
        try:
            print("[Tracker] Fetching ISS TLE…")
            tle_line1, tle_line2 = fetch_iss_tle()
            print("[Tracker] TLE acquired successfully.")
        except Exception as e:
            print(f"[Tracker] All TLE fetch attempts failed: {e}. Retrying in 10s...")
            time.sleep(10)
    print(f"[Tracker] Starting updates every {UPDATE_INTERVAL_S}s\n")

    # Update loop
    while True:
        try:
            lat, lon, alt = get_sat_position(tle_line1, tle_line2)
            positions_history.append((lat, lon, alt))
            idx = len(positions_history)
            print(f"[Tracker] #{idx}: lat={lat:.6f}, lon={lon:.6f}, alt={alt:.2f} km")
        except Exception as e:
            print(f"[Tracker] Position fetch error: {e}")
        time.sleep(UPDATE_INTERVAL_S)


@app.route("/live.kml")
def stream_kml():
    if not positions_history:
        return Response("", status=204)

    lat, lon, alt = positions_history[-1]
    alt_m = alt * 1000
    # Compute heading and tilt
    dist_km = haversine_km(lat, lon, TARGET_LAT, TARGET_LON)
    heading = bearing_deg(lat, lon, TARGET_LAT, TARGET_LON)
    horizontal_m = dist_km * 1000
    tilt_rad = math.atan2(horizontal_m, alt_m)
    tilt_deg = math.degrees(tilt_rad)

    # Camera
    camera = f"""
    <Camera>
      <longitude>{lon:.6f}</longitude>
      <latitude>{lat:.6f}</latitude>
      <altitude>{alt_m:.1f}</altitude>
      <heading>{heading:.1f}</heading>
      <tilt>{tilt_deg:.1f}</tilt>
      <roll>0</roll>
      <altitudeMode>absolute</altitudeMode>
    </Camera>"""

    # Target style and placemark
    style = f"""
    <Style id=\"targetStyle\">
      <IconStyle>
        <color>{TARGET_COLOR}</color>
        <scale>1.3</scale>
        <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>
      </IconStyle>
    </Style>"""
    target_pm = f"""
    <Placemark>
      <name>{TARGET_NAME}</name>
      <styleUrl>#targetStyle</styleUrl>
      <Point>
        <coordinates>{TARGET_LON:.6f},{TARGET_LAT:.6f},{alt_m:.1f}</coordinates>
      </Point>
    </Placemark>"""

    # Waypoints
    placemarks = ""
    for i, (la, lo, al) in enumerate(positions_history, start=1):
        placemarks += f"""
    <Placemark>
      <name>Waypoint {i}</name>
      <Point>
        <coordinates>{lo:.6f},{la:.6f},{al*1000:.1f}</coordinates>
      </Point>
    </Placemark>"""

    kml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml xmlns=\"http://www.opengis.net/kml/2.2\">  
  <Document>
    <name>Real-Time ISS Tracker</name>
    {style}
    {camera}
    {target_pm}
    {placemarks}
  </Document>
</kml>"""
    return Response(kml, mimetype="application/vnd.google-earth.kml+xml")


def shutdown_handler(sig, frame):
    print("\n[Tracker] Exiting gracefully. Goodbye! 👋")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown_handler)
    threading.Thread(target=satellite_updater, daemon=True).start()
    print("[Tracker] Flask server starting on port 5003")
    app.run(host="0.0.0.0", port=5003)

    print("[Tracker] Flask server started successfully.")