import time
import urllib.request
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
import numpy as np
from beyond.io.tle import Tle
from beyond.frames import create_station
from beyond.dates import Date, timedelta
from beyond.env.solarsystem import get_body
from beyond.propagators.listeners import RadialVelocityListener, LightListener

R_TERRA = 6378.137

NORAD_ID = 25544
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={}&FORMAT=TLE".format(NORAD_ID)
BASE = Path(__file__).resolve().parent
TLE_CACHE = BASE / "tle_{}.txt".format(NORAD_ID)
TLE_MAX_AGE = 6 * 3600
IMG = BASE / "images" / "terra2.jpg"
ORBIT_OUT = BASE / "orbit3d.txt"
KSC = (28.524058, -80.65085, 0.0)
MIN_ELEV = 10.0
SOLE_MAX_ELEV = -6.0
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


def write_orbit(path, name, orbit_pts, sat_pt, ksc_pt, sun_dir):
    with open(path, "w") as f:
        f.write(name.strip() + "\n")
        f.write("{:.3f} {:.3f} {:.3f}\n".format(*sat_pt))
        f.write("{:.3f} {:.3f} {:.3f}\n".format(*ksc_pt))
        f.write("{:.6f} {:.6f} {:.6f}\n".format(*sun_dir))
        for p in orbit_pts:
            f.write("{:.3f} {:.3f} {:.3f}\n".format(*p))


tle = load_tle()
print("TLE: {} (epoca {:%Y-%m-%d %H:%M} UTC)".format(tle.name, tle.epoch.datetime))

station = create_station('KSC', KSC)
riferimento = "{} ({:.2f}°{}, {:.2f}°{})".format(
    station.name, abs(KSC[0]), 'N' if KSC[0] >= 0 else 'S', abs(KSC[1]), 'E' if KSC[1] >= 0 else 'O')

sun = get_body('Sun')
luce = LightListener()

start = Date.now()

azims, elevs = [], []
dates, dopplers = [], []
illuminati, sole_elevs = [], []
pass_events = {}

for orb in station.visibility(tle.orbit(), start=start, stop=timedelta(days=1), step=timedelta(seconds=10), events=[RadialVelocityListener(station, sight=True), luce]):
    azim = -np.degrees(orb.theta) % 360
    elev = np.degrees(orb.phi)
    r = orb.r / 1000.
    doppler = -F0 * orb.r_dot / C

    azims.append(azim)
    elevs.append(elev)
    dates.append(orb.date.datetime)
    dopplers.append(doppler)
    illuminati.append(luce(orb) > 0)
    sole_elevs.append(np.degrees(sun.propagate(orb.date).copy(frame=station, form='spherical').phi))

    if orb.event is not None:
        print("{event:15} {tle.name}  {date:%Y-%m-%dT%H:%M:%S.%f} {azim:7.2f} {elev:7.2f} {r:10.2f} {doppler:+9.1f}".format(
            date=orb.date, r=r, azim=azim, elev=elev, doppler=doppler,
            tle=tle, event=orb.event.info
        ))
        pass_events.setdefault(orb.event.info, (orb.date, azim, elev))

    if orb.event and orb.event.info == "LOS":
        max_elev_pass = max(elevs)
        if max_elev_pass >= MIN_ELEV:
            break
        print("Passaggio scartato: elevazione massima {:.1f}° < {}°".format(max_elev_pass, MIN_ELEV))
        azims, elevs = [], []
        dates, dopplers = [], []
        illuminati, sole_elevs = [], []
        pass_events = {}

if "MAX" in pass_events and "LOS" in pass_events:
    aos_date = pass_events["AOS"][0] if "AOS" in pass_events else start
    max_date, max_azim, max_elev = pass_events["MAX"]
    los_date = pass_events["LOS"][0]
    direzione = PUNTI_CARDINALI[int((max_azim + 22.5) // 45) % 8]
    durata = (los_date - aos_date).total_seconds() / 60
    print("Prossimo passaggio da {}: {:%H:%M} UTC  max {:.0f}° a {}  durata {:.0f} min".format(
        riferimento, aos_date.datetime, max_elev, direzione, durata))

    visibili = [d for d, lit, se in zip(dates, illuminati, sole_elevs) if lit and se < SOLE_MAX_ELEV]
    if visibili:
        print("Visibile a occhio nudo: {:%H:%M} - {:%H:%M} UTC".format(visibili[0], visibili[-1]))
    elif min(sole_elevs) >= SOLE_MAX_ELEV:
        print("Non visibile a occhio nudo: cielo troppo chiaro (sole a {:.0f}°)".format(max(sole_elevs)))
    elif not any(illuminati):
        print("Non visibile a occhio nudo: satellite nell'ombra della Terra")
    else:
        print("Non visibile a occhio nudo: satellite in ombra quando il cielo è buio")
else:
    print("Nessun passaggio sopra {}° da {} nelle prossime 24 ore".format(MIN_ELEV, riferimento))

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
print("Posizione attuale: {:.2f}°{}, {:.2f}°{}".format(
    abs(lat), 'N' if lat >= 0 else 'S', abs(lon), 'E' if lon >= 0 else 'O'))

sat_pt = np.array(now.copy(frame='ITRF', form='cartesian')[:3]) / 1000.
st = np.radians(KSC[:2])
ksc_pt = R_TERRA * np.array([np.cos(st[0]) * np.cos(st[1]), np.cos(st[0]) * np.sin(st[1]), np.sin(st[0])])
sun_pt = np.array(sun.propagate(start).copy(frame='ITRF', form='cartesian')[:3])
sun_dir = sun_pt / np.linalg.norm(sun_pt)
write_orbit(ORBIT_OUT, tle.name, orbit_pts, sat_pt, ksc_pt, sun_dir)
print("Scritto {}".format(ORBIT_OUT.name))

im = plt.imread(IMG)
fig_map, ax_map = plt.subplots(figsize=(15.2, 8.2))
ax_map.imshow(im, extent=[-180, 180, -90, 90])

for lons, lats in zip(longitudes, latitudes):
    ax_map.plot(lons, lats, 'w', linestyle=':', linewidth=3)

ax_map.plot([lon], [lat], 'ro')

ax_map.set_xlim([-180, 180])
ax_map.set_ylim([-90, 90])

ax_map.grid(True, color='w', linestyle=':', alpha=0.4)

ax_map.set_xticks(range(-180, 181, 30))
ax_map.set_yticks(range(-90, 91, 30))
fig_map.tight_layout()

fig_pol, ax_pol = plt.subplots(subplot_kw={'projection': 'polar'})
ax_pol.set_theta_direction(-1)
ax_pol.set_theta_zero_location('N')
ax_pol.plot(np.radians(azims), 90 - np.array(elevs), '.')
ax_pol.set_yticks(range(0, 90, 20))
ax_pol.set_yticklabels(map(str, range(90, 0, -20)))
ax_pol.set_rmax(90)

fig, (ax, ax_el) = plt.subplots(2, 1, sharex=True, figsize=(7, 6), height_ratios=[2, 1])
t = mdates.date2num(dates)
d = np.array(dopplers) / 1000.
# Inserisce lo zero interpolato tra campioni di segno opposto, così le due curve si toccano
i = np.where(np.sign(d[:-1]) * np.sign(d[1:]) < 0)[0]
t = np.insert(t, i + 1, t[i] - d[i] * (t[i + 1] - t[i]) / (d[i + 1] - d[i]))
d = np.insert(d, i + 1, 0.)
t = mdates.num2date(t)
for segno, colore, etichetta in [(1, 'tab:blue', "Avvicinamento"), (-1, 'tab:red', "Allontanamento")]:
    tratto = segno * d >= 0
    ax.plot(t, np.where(tratto, d, np.nan), color=colore, label=etichetta)
    ax.fill_between(t, d, 0, where=tratto, color=colore, alpha=0.15, linewidth=0)
ax.legend(loc='upper right')
ax.axhline(0, color='k', linewidth=0.5)
ax.set_ylabel("Doppler a {:.3f} MHz [kHz]".format(F0 / 1e6))
ax.grid(True, linestyle=':')

titolo = "{}  ·  f0 {:.3f} MHz  ·  {}".format(tle.name.strip(), F0 / 1e6, riferimento)
if dates:
    titolo += "\n{:%Y-%m-%d}  ·  elevazione max {:.0f}°".format(dates[0], max(elevs))
ax.set_title(titolo, fontsize=10)

# Frequenza da sintonizzare in ricezione: f0 + Δf
f0_mhz = F0 / 1e6
ax_f = ax.secondary_yaxis('right', functions=(lambda khz: f0_mhz + khz / 1000., lambda mhz: (mhz - f0_mhz) * 1000.))
ax_f.set_ylabel("Frequenza da sintonizzare [MHz]")
ax_f.yaxis.set_major_formatter(FormatStrFormatter('%.4f'))

ax_el.plot(dates, elevs, color='k')
ax_el.axhline(MIN_ELEV, color='gray', linestyle='--', linewidth=1)
ax_el.axhspan(0, MIN_ELEV, color='gray', alpha=0.15, linewidth=0)
ax_el.set_ylim(bottom=0)
ax_el.set_xlabel("UTC")
ax_el.set_ylabel("Elevazione [°]")
ax_el.grid(True, linestyle=':')
fig.autofmt_xdate()
fig.tight_layout()

plt.show()
