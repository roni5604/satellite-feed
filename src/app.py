import threading
import time
import logging
import signal
import sys
import math
import requests
from skyfield.api import load, EarthSatellite, wgs84
from flask import Flask, Response
import random


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
                       shift_prob=0.0):   # y: chance [0.0–1.0]
    """
    Precompute ground-projected targets.
    Optionally shift some laterally (left/right) up to `max_shift_km` with probability `shift_prob`.
    """
    global target_points, tle_line1, tle_line2
    ts  = load.timescale()
    sat = EarthSatellite(tle_line1, tle_line2, "ISS", ts)

    now   = ts.now()
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
    # global tle_line1, tle_line2, target_lat_dyn, target_lon_dyn
    global tle_line1, tle_line2
    if tle_line1 is None:  # first run only
        print("[Tracker] Fetching ISS TLE…")
        tle_line1, tle_line2 = fetch_iss_tle()
        print("[Tracker] TLE acquired.")

    # # 1) Compute the timestamp LEAD_TIME_S seconds in the future:
    # ts = load.timescale()
    # t_future = ts.now() + (LEAD_TIME_S / 86400.0)  # Skyfield uses days, so seconds/86400.
    #
    # # 2) Get ISS’s predicted position at t_future:
    # fut_lat, fut_lon, fut_alt = get_sat_position(tle_line1, tle_line2, when=t_future)
    # # We only need ground projection (altitude=0) for the target:
    # target_lat_dyn = fut_lat
    # target_lon_dyn = fut_lon
    # print(
    #     f"[Tracker] Lead-Track Target set → lat {target_lat_dyn:.6f}, lon {target_lon_dyn:.6f} (ground, alt=0)"
    # )
    #
    # print(f"[Tracker] Starting updates every {UPDATE_INTERVAL_S}s\n")

    while True:
        # 3) Compute current ISS position (lat, lon, alt_km):
        lat, lon, alt_km = get_sat_position(tle_line1, tle_line2)
        positions_history.append((lat, lon, alt_km))
        idx = len(positions_history)

        # # 4) Compute horizontal distance (km) from ISS to the fixed target:
        # horiz_dist_km = haversine_km(lat, lon, target_lat_dyn, target_lon_dyn)
        #
        # # 5) Compute bearing (heading) from ISS → target:
        # heading = bearing_deg(lat, lon, target_lat_dyn, target_lon_dyn)
        #
        # # 6) Compute elevation angle (°) of ISS as seen from the target:
        # if horiz_dist_km > 0.0:
        #     elev_rad = math.atan2(alt_km, horiz_dist_km)
        #     elev_deg = math.degrees(elev_rad)
        # else:
        #     elev_deg = 90.0  # Directly overhead
        #
        # # 7) Compute tilt for KML: tilt = 90° − elevation
        # #    (0° = straight down, 90° = horizon view)
        # tilt = max(0.0, min(90.0, 90.0 - elev_deg))
        #
        # # 8) Compute the exact slant distance (km) from ISS → target:
        # slant_dist_km = math.sqrt(horiz_dist_km**2 + alt_km**2)
        # #    Convert to meters:
        # slant_dist_m = slant_dist_km * 1000.0
        # # 9) Adjust the range so camera sits ALT_OFFSET_M lower along that LOS:
        # adjusted_range_m = max(1.0, slant_dist_m - ALT_OFFSET_M)
        #
        # # 10) Print current ISS position and LookAt parameters:
        # print(
        #     f"[Tracker] #{idx}: ISS lat={lat:.6f}, lon={lon:.6f}, alt={alt_km:.2f} km"
        # )
        # print(
        #     f"           → heading={heading:.1f}°, tilt={tilt:.1f}°, "
        #     f"range={adjusted_range_m:.1f} m  (original slant={slant_dist_m:.1f} m)"
        # )

        time.sleep(UPDATE_INTERVAL_S)


# @app.route("/live.kml")
# def stream_kml():
#     """
#     Streams a KML document where:
#       - The camera’s LookAt “looks from” the current ISS position
#         “toward” the fixed lead-track target on the ground.
#       - We compute heading, tilt, and an adjusted range (slant − ALT_OFFSET_M),
#         so the camera appears slightly lower than the precise slant line.
#       - We also draw a Placemark for the fixed ground target (icon at alt=0)
#         and a Placemark for each recorded ISS waypoint.
#     """
#     global target_lat_dyn, target_lon_dyn
#
#     if not positions_history or target_lat_dyn is None:
#         # No data yet → return “204 No Content”
#         return Response("", status=204)
#
#     # 1) Get most recent ISS position (lat, lon, alt_km)
#     sat_lat, sat_lon, sat_alt_km = positions_history[-1]
#
#     # 2) Compute horizontal distance (km) between ISS and the fixed target:
#     dist_km = haversine_km(sat_lat, sat_lon, target_lat_dyn, target_lon_dyn)
#
#     # 3) Compute bearing (heading) from ISS → target:
#     heading = bearing_deg(sat_lat, sat_lon, target_lat_dyn, target_lon_dyn)
#
#     # 4) Compute elevation of ISS as seen from target:
#     if dist_km > 0.0:
#         elev_rad = math.atan2(sat_alt_km, dist_km)
#         elev_deg = math.degrees(elev_rad)
#     else:
#         elev_deg = 90.0
#
#     # 5) Compute tilt for KML: tilt = 90° − elevation
#     tilt = max(0.0, min(90.0, 90.0 - elev_deg))
#
#     # 6) Compute exact slant distance (km) from ISS → target, then convert to meters
#     slant_dist_km = math.sqrt(dist_km**2 + sat_alt_km**2)
#     slant_dist_m = slant_dist_km * 1000.0
#
#     # 7) Adjust range so camera is ALT_OFFSET_M lower:
#     adjusted_range_m = max(1.0, slant_dist_m - ALT_OFFSET_M)
#
#     # 8) Build the <LookAt> element: always “looks at” the ground‐target (alt=0)
#     lookat = f"""
#     <LookAt>
#       <longitude>{target_lon_dyn:.6f}</longitude>
#       <latitude>{target_lat_dyn:.6f}</latitude>
#       <altitude>0</altitude>
#       <range>{adjusted_range_m:.1f}</range>
#       <tilt>{tilt:.1f}</tilt>
#       <heading>{heading:.1f}</heading>
#       <altitudeMode>absolute</altitudeMode>
#     </LookAt>"""
#
#     # 9) Style for the fixed ground target icon
#     style = f"""
#     <Style id="targetStyle">
#       <IconStyle>
#         <color>{TARGET_COLOR}</color>
#         <scale>1.3</scale>
#         <Icon>
#           <href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>
#         </Icon>
#       </IconStyle>
#     </Style>"""
#
#     # 10) Placemark for the fixed ground target (alt=0)
#     target_pm = f"""
#     <Placemark>
#       <name>{TARGET_NAME}</name>
#       <styleUrl>#targetStyle</styleUrl>
#       <Point>
#         <coordinates>{target_lon_dyn:.6f},{target_lat_dyn:.6f},0</coordinates>
#       </Point>
#     </Placemark>"""
#
#     # 11) Placemarks for every recorded ISS waypoint:
#     placemarks = ""
#     for i, (la, lo, al) in enumerate(positions_history, start=1):
#         placemarks += f"""
#     <Placemark>
#       <name>ISS Waypoint {i}</name>
#       <Point>
#         <coordinates>{lo:.6f},{la:.6f},{al*1000.0:.1f}</coordinates>
#       </Point>
#     </Placemark>"""
#
#     # 12) Assemble full KML document
#     kml = f"""<?xml version="1.0" encoding="UTF-8"?>
# <kml xmlns="http://www.opengis.net/kml/2.2">
#   <Document>
#     <name>Real-Time ISS Tracker (Lead-Track Target, Lower Altitude)</name>
#     {style}
#     {lookat}
#     {target_pm}
#     {placemarks}
#   </Document>
# </kml>"""
#
#     return Response(kml, mimetype="application/vnd.google-earth-kml+xml")

@app.route("/live.kml")
def stream_kml():
    """
    * Camera viewpoint = current ISS position
    * Camera looks at the *nearest* target point (if any)
    * Every target point and ISS waypoint is drawn as a Placemark
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
    # print the closest target point and the distance
    dist_km = haversine_km(sat_lat, sat_lon, tgt_lat, tgt_lon)
    print(f"[Tracker] Closest target: lat={tgt_lat:.6f}, lon={tgt_lon:.6f}, Distance: {dist_km:.1f} km")

    # 3)  Geometry from ISS → target
    heading = bearing_deg(sat_lat, sat_lon, tgt_lat, tgt_lon)
    elev_deg = math.degrees(math.atan2(sat_alt_km, dist_km)) if dist_km else 90.0
    tilt = max(0.0, min(90.0, 90.0 - elev_deg))
    slant_dist_m = math.sqrt(dist_km ** 2 + sat_alt_km ** 2) * 1000.0
    adjusted_m = max(1.0, slant_dist_m - ALT_OFFSET_M)

    # ------------------------------------------------------------------
    # 4)  Assemble KML
    lookat = f"""
    <LookAt>
      <longitude>{tgt_lon:.6f}</longitude>
      <latitude>{tgt_lat:.6f}</latitude>
      <altitude>0</altitude>
      <range>{adjusted_m:.1f}</range>
      <tilt>{tilt:.1f}</tilt>
      <heading>{heading:.1f}</heading>
      <altitudeMode>absolute</altitudeMode>
    </LookAt>"""

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

    # ---------- Placemarks ----------
    # a) Target points
    placemarks = ""
    for i, (la, lo) in enumerate(target_points, start=1):
        placemarks += f"""
    <Placemark>
      <name>{TARGET_NAME_PREFIX} {i}</name>
      <styleUrl>#targetStyle</styleUrl>
      <Point>
        <coordinates>{lo:.6f},{la:.6f},0</coordinates>
      </Point>
    </Placemark>"""

    # b) ISS way-points (altitude in metres)
    for i, (la, lo, al) in enumerate(positions_history, start=1):
        placemarks += f"""
    <Placemark>
      <name>ISS Waypoint {i}</name>
      <Point>
        <coordinates>{lo:.6f},{la:.6f},{al * 1000:.1f}</coordinates>
      </Point>
    </Placemark>"""

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Real-Time ISS Tracker – Orbit Targets</name>
    {style}
    {lookat}
    {placemarks}
  </Document>
</kml>"""
    return Response(kml, mimetype="application/vnd.google-earth-kml+xml")


def shutdown_handler(sig, frame):
    """
    Graceful shutdown handler (e.g., on Ctrl+C).
    """
    print("\n[Tracker] Exiting gracefully. Goodbye! 👋")
    sys.exit(0)


if __name__ == "__main__":
    # Catch SIGINT (Ctrl+C) to exit cleanly
    # 1)  Fetch ISS TLE so everybody can share it
    tle_line1, tle_line2 = fetch_iss_tle()

    # 2)  Fill `target_points` for the next 90 min (or whatever you chose)
    # precompute_targets()
    precompute_shifted_targets(max_shift_km=100.0, shift_prob=0.3)  # Example with shifting

    # 3)  Normal start-up
    signal.signal(signal.SIGINT, shutdown_handler)
    threading.Thread(target=satellite_updater, daemon=True).start()
    print("[Tracker] Flask server on port 5003 …")
    app.run(host="0.0.0.0", port=5003)

"""
    ToDo:
    - add more camera targets                                       V
    - make the target shift off course by up to X kilometers
    - make the camara look at the closest target                    V

    - add info gui with:
     speed, angle, camera angle, distance to the closest target and the secound closest (with directions)

    - add laser beams from the sat location to the distance 



"""
