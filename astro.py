import time
import urllib.request
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from beyond.io.tle import Tle
from beyond.frames import create_station
from beyond.dates import Date, timedelta
from beyond.propagators.listeners import RadialVelocityListener

R_TERRA = 6378.137

NORAD_ID = 25544
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={}&FORMAT=TLE".format(NORAD_ID)
BASE = Path(__file__).resolve().parent
TLE_CACHE = BASE / "tle_{}.txt".format(NORAD_ID)
TLE_MAX_AGE = 6 * 3600
IMG = BASE / "images" / "terra2.jpg"
ORBIT_OUT = BASE / "orbit3d.txt"
KSC = (28.524058, -80.65085, 0.0)
F0 = 145.800e6
C = 299792458.
PUNTI_CARDINALI = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO']


def load_tle():
    if TLE_CACHE.exists() and time.time() - TLE_CACHE.stat().st_mtime < TLE_MAX_AGE:
        return Tle(TLE_CACHE.read_text())
    try:
        with urllib.request.urlopen(TLE_URL, timeout=15) as resp:
            text = resp.read().decode().strip()
        tle = Tle(text)
        TLE_CACHE.write_text(text)
        return tle
    except Exception as e:
        if TLE_CACHE.exists():
            print("Download TLE fallito ({}), uso la copia locale".format(e))
            return Tle(TLE_CACHE.read_text())
        raise


def write_orbit(path, name, orbit_pts, sat_pt, ksc_pt):
    with open(path, "w") as f:
        f.write(name.strip() + "\n")
        f.write("{:.3f} {:.3f} {:.3f}\n".format(*sat_pt))
        f.write("{:.3f} {:.3f} {:.3f}\n".format(*ksc_pt))
        for p in orbit_pts:
            f.write("{:.3f} {:.3f} {:.3f}\n".format(*p))


tle = load_tle()
print("TLE: {} (epoca {:%Y-%m-%d %H:%M} UTC)".format(tle.name, tle.epoch.datetime))

station = create_station('KSC', KSC)
riferimento = "{} ({:.2f}°{}, {:.2f}°{})".format(
    station.name, abs(KSC[0]), 'N' if KSC[0] >= 0 else 'S', abs(KSC[1]), 'E' if KSC[1] >= 0 else 'O')

start = Date.now()

azims, elevs = [], []
dates, dopplers = [], []
pass_events = {}

for orb in station.visibility(tle.orbit(), start=start, stop=timedelta(days=1), step=timedelta(seconds=10), events=RadialVelocityListener(station, sight=True)):
    azim = -np.degrees(orb.theta) % 360
    elev = np.degrees(orb.phi)
    r = orb.r / 1000.
    doppler = -F0 * orb.r_dot / C

    azims.append(azim)
    elevs.append(elev)
    dates.append(orb.date.datetime)
    dopplers.append(doppler)

    print("{event:15} {tle.name}  {date:%Y-%m-%dT%H:%M:%S.%f} {azim:7.2f} {elev:7.2f} {r:10.2f} {doppler:+9.1f}".format(
        date=orb.date, r=r, azim=azim, elev=elev, doppler=doppler,
        tle=tle, event=orb.event.info if orb.event is not None else ""
    ))

    if orb.event is not None:
        pass_events.setdefault(orb.event.info, (orb.date, azim, elev))

    if orb.event and orb.event.info == "LOS":
        break

if "MAX" in pass_events and "LOS" in pass_events:
    aos_date = pass_events["AOS"][0] if "AOS" in pass_events else start
    max_date, max_azim, max_elev = pass_events["MAX"]
    los_date = pass_events["LOS"][0]
    direzione = PUNTI_CARDINALI[int((max_azim + 22.5) // 45) % 8]
    durata = (los_date - aos_date).total_seconds() / 60
    print("Prossimo passaggio visibile da {}: {:%H:%M} UTC  max {:.0f}° a {}  durata {:.0f} min".format(
        riferimento, aos_date.datetime, max_elev, direzione, durata))
else:
    print("Nessun passaggio visibile da {} nelle prossime 24 ore".format(riferimento))

orb = tle.orbit()

latitudes, longitudes = [], []
orbit_pts = []
prev_lon, prev_lat = None, None

period = orb.infos.period

stop = 1 * period
step = period / 100

for point in orb.ephemeris(start=start, stop=stop, step=step):
    point.frame = 'ITRF'

    orbit_pts.append(point.copy(form='cartesian')[:3] / 1000.)

    point.form = 'spherical'

    lon, lat = np.degrees(point[1:3])

    if prev_lon is None:
        lons = []
        lats = []
        longitudes.append(lons)
        latitudes.append(lats)
    elif abs(lon - prev_lon) > 180:
        shift = -360 if lon > prev_lon else 360
        lons.append(lon + shift)
        lats.append(lat)
        lons = [prev_lon - shift]
        lats = [prev_lat]
        longitudes.append(lons)
        latitudes.append(lats)

    lons.append(lon)
    lats.append(lat)
    prev_lon = lon
    prev_lat = lat

now = orb.propagate(start)
lon, lat = np.degrees(now.copy(frame='ITRF', form='spherical')[1:3])
print("%s %s" % (lon, lat))

sat_pt = np.array(now.copy(frame='ITRF', form='cartesian')[:3]) / 1000.
st = np.radians(KSC[:2])
ksc_pt = R_TERRA * np.array([np.cos(st[0]) * np.cos(st[1]), np.cos(st[0]) * np.sin(st[1]), np.sin(st[0])])
write_orbit(ORBIT_OUT, tle.name, orbit_pts, sat_pt, ksc_pt)
print("Scritto {}".format(ORBIT_OUT.name))

im = plt.imread(IMG)
plt.figure(figsize=(15.2, 8.2))
plt.imshow(im, extent=[-180, 180, -90, 90])

for lons, lats in zip(longitudes, latitudes):
    plt.plot(lons, lats, 'w', linestyle=':', linewidth=3)

plt.plot([lon], [lat], 'ro')

plt.xlim([-180, 180])
plt.ylim([-90, 90])

plt.grid(True, color='w', linestyle=':', alpha=0.4)

plt.xticks(range(-180, 181, 30))
plt.yticks(range(-90, 91, 30))
plt.tight_layout()

plt.figure()
ax = plt.subplot(111, projection='polar')
ax.set_theta_direction(-1)
ax.set_theta_zero_location('N')
plt.plot(np.radians(azims), 90 - np.array(elevs), '.')
ax.set_yticks(range(0, 90, 20))
ax.set_yticklabels(map(str, range(90, 0, -20)))
ax.set_rmax(90)

plt.figure()
plt.plot(dates, np.array(dopplers) / 1000.)
plt.axhline(0, color='k', linewidth=0.5)
plt.xlabel("UTC")
plt.ylabel("Doppler a {:.3f} MHz [kHz]".format(F0 / 1e6))
plt.grid(True, linestyle=':')
plt.gcf().autofmt_xdate()

plt.show()
