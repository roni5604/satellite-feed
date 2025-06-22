# ISS Real-Time Tracker Simulation

## 📜 Overview
This final project for the Ariel University Space Engineering course implements a real-time simulation of the International Space Station (ISS) orbiting Earth. Our objectives are:
- **Track ISS position** in real time using the Skyfield library and live TLE data from Celestrak.
- **Visualize** the ISS camera “view” in Google Earth via dynamically generated KML.
- **Demonstrate** two modes:
  1. **Static Look-Down** (heading = 0°, tilt = 0°) showing a north-down view.
  2. **Dynamic Targeting**, where the ISS “locks on” to ground targets defined at runtime and adjusts heading and tilt accordingly.
- **Display** satellite attitude and energy consumption in two GUIs:
  - A Tkinter-based **Simulation GUI** (heading/tilt rates & energy).
  - A PySide6 + PyQtGraph **3D Satellite Viewer** (attitude in 3D).

## ⚙️ Installation & Setup

### 1. Clone the repository
```bash
git clone https://github.com/roni5604/satellite-feed.git
cd satellite-feed
````

### 2. Create & activate a Python virtual environment

> **macOS / Linux**

```bash
python3 -m venv venv
source venv/bin/activate
```

> **Windows (PowerShell)**

```powershell
python3 -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install requirements

```bash
pip install -r requirements.txt
```

### 4. Run the simulation backend

```bash
python app.py
```

### 5. Launch the Simulation GUI

*In a new terminal (with venv active):*

```bash
python simulation_gui.py
python simulation_gui_2.py
```

### 6. Launch the 3D Satellite Viewer

*In another terminal (with venv active):*

```bash
python satellite_gui.py
```

### 7. Start KML stream in Google Earth Pro

1. **Edit** the `networklink.kml` file (it lives in the repo root) so that its `<href>` points at your machine’s LAN IP instead of `localhost`. For example, if your PC’s IP is `10.100.102.26`, change:

   ```xml
   <NetworkLink>
     <name>ISS Tracker</name>
     <refreshMode>onInterval</refreshMode>
     <refreshInterval>5</refreshInterval>
     <Link>
       <href>http://10.100.102.26:5003/dynamic.kml</href>
     </Link>
   </NetworkLink>
   ```

2. **Find your local IP** on the same network (see below).

3. In Google Earth Pro choose **File → Open…**, select this edited `networklink.kml`, and click **Open**. It will then pull your live stream and refresh every 5 seconds.

---

### 🔍 How to discover your machine’s IP address

* **Windows**:
  Open PowerShell or CMD and run `ipconfig`. Look for the “IPv4 Address” under your active adapter (Ethernet or Wi-Fi).

* **macOS / Linux**:
  Open Terminal and run `ifconfig` or `ip addr show`. Your IP is listed next to `inet` on the interface you’re using (e.g. `en0`, `wlan0`).

Once you know the IP (e.g. `192.168.1.42`), replace **`10.100.102.26`** above with **your** IP.


---


## 🎥 Demonstration Video
The demonstration video file **`final_video.mov`** is located in the project root.  
To view it, open `final_video.mov` with your preferred media player, or click the link below:

[▶️ Play Demo Video](https://drive.google.com/file/d/1JhUz0Zecrq9HHuNc67pvaG3HO3MYRr7L/view)

[▶️ Play New Version Demo]((https://drive.google.com/file/d/12TNvrS-UMboLWRBlGWjw_YkyLtWeyes8/view))


---

## 🔧 Detailed Explanation: `app.py`

1. **TLE Fetch & Parsing**

   * Downloads ISS Two-Line Element (TLE) from Celestrak.
2. **Position Computation**

   * Uses **Skyfield** to compute geodetic latitude, longitude, and altitude every 5 s.
3. **KML Generation**

   * **Orbit-only** mode: generates `orbit.kml` with a straight-down view (heading = 0°, tilt = 0°).
   * **Focus** mode:

     * Precomputes a series of ground targets.
     * Picks the nearest target each update.
     * Computes **heading** via `bearing_deg()` (0° = north, 90° = east…).
     * Computes **tilt** from elevation angle:

       ```python
       elev_deg = atan2(sat_alt_km, dist_km)
       tilt = 90° - elev_deg
       ```
     * Writes `dynamic.kml` with `<LookAt>` updated range, heading, tilt.
4. **Angular Rates & Energy**

   * Calculates heading/tilt rate (deg/s) from successive positions.
   * Energy use ≃ 5 W idle + coefficients·(rate²) + focus overhead.
5. **Flask API**

   * Serves `/state` (focus\_mod, heading\_rate, tilt\_rate) and `/angles` (heading, tilt) for GUIs.

---

## 🖥️ Satellite GUI (`satellite_gui.py`)

* **Framework:** PySide6 + PyQtGraph (OpenGL).
* **3D View:**

  * Loads an STL model of the satellite, centers it at fixed altitude.
  * Applies rotation: yaw = heading, pitch = tilt.
* **Side Panel:**

  * Displays numeric **Heading** & **Tilt** values (polled from `/angles`).
  * Updates every 5 s to reflect real-time attitude.
* **Status Bar:**

  * Shows camera parameters (distance, elevation, azimuth).

---

## 🖱️ Simulation GUI (`simulation_gui.py`)

* **Framework:** Tkinter + ttk.
* **Controls:**

  * **Start/Stop Focus** button toggles static vs focus mode.
* **Displays:**

  * **Heading Rate** (deg/s) & **Tilt Rate** (deg/s) as progress bars.
  * **Energy Use** (W) computed each update.
* **Updates:**

  * Polls Flask `/state` endpoint every 100 ms.

---

## 📂 Project Structure

```
satellite-feed/
├─ app.py
├─ simulation_gui.py
├─ satellite_gui.py
├─ satellite_gui_2.py
├─ shared_state.py
├─ requirements.txt
├─ static/
│  └─ pod_box.stl
└─ README.md       ← (this file)
```

---

## 👥 Authors

* **Roni Michaeli** (209233873)
* **Neta Cohen** (325195774)
* **Matan Ziv** (208235796)

---

## 📖 Additional Notes

* Tested on Ubuntu/macOS/Windows with Python 3.10+.
* Requires Google Earth Pro for KML visualization.
* Ensure network access to `localhost:5003` for live feeds.
* Modify `TARGET_INTERVAL_S`, `UPDATE_INTERVAL_S` in `app.py` for faster/slower updates.


