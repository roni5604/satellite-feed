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
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# ========================
#  קביעות והגדרות:
# ========================
TLE_URL            = "https://celestrak.com/NORAD/elements/stations.txt"
UPDATE_INTERVAL_S  = 5          # עדכון כל 5 שניות
LOOKAT_RANGE_M     = 700_000    # מרחק צפייה קבוע (700 ק"מ)
FOCUS_DISTANCE_KM  = 500        # רדיוס למעבר לזווית 90°

# הגדר את נקודת היעד כאן:
TARGET_LAT   = 31.8           # קו רוחב
TARGET_LON   = 35.2           # קו אורך
TARGET_NAME  = "Target Site"  # שם משמעותי
# צבע ב־AABBGGRR (אדום מלא): FF0000FF
TARGET_COLOR = "ff0000ff"     

# היסטוריה של מיקומים [(lat, lon, alt_km), ...]
positions_history = []
tle_line1 = tle_line2 = None

def fetch_iss_tle():
    r = requests.get(TLE_URL, timeout=10)
    lines = r.text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("ISS (ZARYA)"):
            return lines[i+1].strip(), lines[i+2].strip()
    raise RuntimeError("ISS TLE not found")

def get_sat_position(line1, line2):
    ts  = load.timescale()
    sat = EarthSatellite(line1, line2, name="ISS", ts=ts)
    t   = ts.now()
    geo = sat.at(t)
    lat, lon = wgs84.latlon_of(geo)
    alt_km   = wgs84.height_of(geo).km
    return float(lat.degrees), float(lon.degrees), float(alt_km)

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = φ2 - φ1
    Δλ = math.radians(lon2 - lon1)
    a = math.sin(Δφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(Δλ/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def bearing_deg(lat1, lon1, lat2, lon2):
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    x = math.sin(Δλ) * math.cos(φ2)
    y = math.cos(φ1)*math.sin(φ2) - math.sin(φ1)*math.cos(φ2)*math.cos(Δλ)
    θ = math.atan2(x, y)
    return (math.degrees(θ) + 360) % 360

def satellite_updater():
    global tle_line1, tle_line2
    print("[Tracker] Fetching ISS TLE…")
    tle_line1, tle_line2 = fetch_iss_tle()
    print(f"[Tracker] TLE acquired. Starting updates every {UPDATE_INTERVAL_S}s\n")
    while True:
        lat, lon, alt = get_sat_position(tle_line1, tle_line2)
        positions_history.append((lat, lon, alt))
        idx = len(positions_history)
        print(f"[Tracker] #{idx}: lat={lat:.6f}, lon={lon:.6f}, alt={alt:.2f} km")
        time.sleep(UPDATE_INTERVAL_S)

@app.route("/live.kml")
def stream_kml():
    if not positions_history:
        return Response("", status=204)

    # מיקום נוכחי
    lat, lon, alt = positions_history[-1]
    alt_m = alt * 1000

    # חישוב מרחק ו-heading לעבר היעד
    dist_km = haversine_km(lat, lon, TARGET_LAT, TARGET_LON)
    heading = bearing_deg(lat, lon, TARGET_LAT, TARGET_LON)
    t = max(0.0, min(1.0, 1 - dist_km / FOCUS_DISTANCE_KM))
    tilt = t * 90.0

    # תבנית LookAt דינמית
    lookat = f"""
    <LookAt>
      <longitude>{lon:.6f}</longitude>
      <latitude>{lat:.6f}</latitude>
      <altitude>{alt_m:.1f}</altitude>
      <range>{LOOKAT_RANGE_M}</range>
      <tilt>{tilt:.1f}</tilt>
      <heading>{heading:.1f}</heading>
      <altitudeMode>absolute</altitudeMode>
    </LookAt>"""

    # הוספת Style ליעד
    style = f"""
    <Style id="targetStyle">
      <IconStyle>
        <color>{TARGET_COLOR}</color>
        <scale>1.3</scale>
        <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>
      </IconStyle>
    </Style>"""

    # Placemark של היעד
    target_pm = f"""
    <Placemark>
      <name>{TARGET_NAME}</name>
      <styleUrl>#targetStyle</styleUrl>
      <Point>
        <coordinates>{TARGET_LON:.6f},{TARGET_LAT:.6f},{alt_m:.1f}</coordinates>
      </Point>
    </Placemark>"""

    # Placemark לכל Waypoint
    placemarks = ""
    for i, (la, lo, al) in enumerate(positions_history, start=1):
        placemarks += f"""
    <Placemark>
      <name>Waypoint {i}</name>
      <Point>
        <coordinates>{lo:.6f},{la:.6f},{al*1000:.1f}</coordinates>
      </Point>
    </Placemark>"""

    # בניית הקובץ המלא
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Real-Time ISS Tracker</name>
    {style}
    {lookat}
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
