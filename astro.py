import argparse
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
from matplotlib.widgets import Button, TextBox
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
F0_DEFAULT_MHZ = 145.800
C = 299792458.
PUNTI_CARDINALI = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO']


@dataclass
class Passaggio:
    start: Date
    dates: list = field(default_factory=list)
    azims: list = field(default_factory=list)
    elevs: list = field(default_factory=list)
    r_dot: list = field(default_factory=list)
    lons: list = field(default_factory=list)         # punto sotto il satellite, per il cursore sulla mappa
    lats: list = field(default_factory=list)
    illuminati: list = field(default_factory=list)
    sole_elevs: list = field(default_factory=list)
    eventi: list = field(default_factory=list)
    scartati: list = field(default_factory=list)

    def evento(self, info):
        return next(((d, az, el) for i, d, az, el, _, _ in self.eventi if i == info), None)

    @property
    def trovato(self):
        return self.evento("MAX") is not None and self.evento("LOS") is not None

    def doppler(self, f0):
        return -f0 * np.array(self.r_dot) / C


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


def find_pass(tle, station, sun, start, min_elev=MIN_ELEV, finestra=timedelta(days=1)):
    luce = LightListener()
    p = Passaggio(start)
    scartati = []

    for orb in station.visibility(tle.orbit(), start=start, stop=finestra, step=timedelta(seconds=10), events=[RadialVelocityListener(station, sight=True), luce]):
        azim = -np.degrees(orb.theta) % 360
        elev = np.degrees(orb.phi)

        p.azims.append(azim)
        p.elevs.append(elev)
        p.dates.append(orb.date.datetime)
        p.r_dot.append(orb.r_dot)
        lon, lat = np.degrees(orb.copy(frame='ITRF', form='spherical')[1:3])
        p.lons.append(lon)
        p.lats.append(lat)
        p.illuminati.append(luce(orb) > 0)
        p.sole_elevs.append(np.degrees(sun.propagate(orb.date).copy(frame=station, form='spherical').phi))

        if orb.event is not None:
            p.eventi.append((orb.event.info, orb.date, azim, elev, orb.r / 1000., orb.r_dot))

        if orb.event and orb.event.info == "LOS":
            if max(p.elevs) >= min_elev:
                break
            scartati.append((p.eventi, max(p.elevs)))
            p = Passaggio(start)

    p.scartati = scartati
    return p


def ground_track(orb, start, n=100):

    latitudes, longitudes = [], []
    orbit_pts = []
    prev_lon, prev_lat = None, None

    period = orb.infos.period

    for point in orb.ephemeris(start=start, stop=period, step=period / n):
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

    return longitudes, latitudes, orbit_pts


def stampa_eventi(eventi, nome, f0):
    for info, date, azim, elev, r, r_dot in eventi:
        print("{event:15} {name}  {date:%Y-%m-%dT%H:%M:%S.%f} {azim:7.2f} {elev:7.2f} {r:10.2f} {doppler:+9.1f}".format(
            date=date, r=r, azim=azim, elev=elev, doppler=-f0 * r_dot / C,
            name=nome, event=info
        ))


def stampa_passaggio(p, nome, f0, riferimento, min_elev=MIN_ELEV):
    for eventi, max_elev_pass in p.scartati:
        stampa_eventi(eventi, nome, f0)
        print("Passaggio scartato: elevazione massima {:.1f}° < {}°".format(max_elev_pass, min_elev))
    stampa_eventi(p.eventi, nome, f0)

    if not p.trovato:
        print("Nessun passaggio sopra {}° da {} nelle 24 ore dopo le {:%Y-%m-%d %H:%M} UTC".format(
            min_elev, riferimento, p.start.datetime))
        return

    aos = p.evento("AOS")
    aos_date = aos[0] if aos else p.start
    max_date, max_azim, max_elev = p.evento("MAX")
    los_date = p.evento("LOS")[0]
    direzione = PUNTI_CARDINALI[int((max_azim + 22.5) // 45) % 8]
    durata = (los_date - aos_date).total_seconds() / 60
    print("Prossimo passaggio da {}: {:%H:%M} UTC  max {:.0f}° a {}  durata {:.0f} min".format(
        riferimento, aos_date.datetime, max_elev, direzione, durata))

    visibili = [d for d, lit, se in zip(p.dates, p.illuminati, p.sole_elevs) if lit and se < SOLE_MAX_ELEV]
    if visibili:
        print("Visibile a occhio nudo: {:%H:%M} - {:%H:%M} UTC".format(visibili[0], visibili[-1]))
    elif min(p.sole_elevs) >= SOLE_MAX_ELEV:
        print("Non visibile a occhio nudo: cielo troppo chiaro (sole a {:.0f}°)".format(max(p.sole_elevs)))
    elif not any(p.illuminati):
        print("Non visibile a occhio nudo: satellite nell'ombra della Terra")
    else:
        print("Non visibile a occhio nudo: satellite in ombra quando il cielo è buio")


def plot_map(ax, longitudes, latitudes, lon, lat):
    ax.imshow(plt.imread(IMG), extent=[-180, 180, -90, 90])

    for lons, lats in zip(longitudes, latitudes):
        ax.plot(lons, lats, 'w', linestyle=':', linewidth=3)

    ax.plot([lon], [lat], 'ro')

    ax.set_xlim([-180, 180])
    ax.set_ylim([-90, 90])

    ax.grid(True, color='w', linestyle=':', alpha=0.4)

    ax.set_xticks(range(-180, 181, 30))
    ax.set_yticks(range(-90, 91, 30))


def plot_polar(ax, p):
    ax.clear()
    ax.set_theta_direction(-1)
    ax.set_theta_zero_location('N')
    ax.plot(np.radians(p.azims), 90 - np.array(p.elevs), '.')
    ax.set_yticks(range(0, 90, 20))
    ax.set_yticklabels(map(str, range(90, 0, -20)))
    ax.set_rmax(90)


def plot_doppler(ax, ax_el, p, f0, nome, riferimento, min_elev=MIN_ELEV):
    # clear() elimina anche l'asse secondario delle frequenze
    ax.clear()
    ax_el.clear()

    if p.dates:
        t = mdates.date2num(p.dates)
        d = p.doppler(f0) / 1000.
        # Inserisce lo zero interpolato tra campioni di segno opposto
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
    ax.set_ylabel("Doppler a {:.3f} MHz [kHz]".format(f0 / 1e6))
    ax.grid(True, linestyle=':')
    ax.tick_params(labelbottom=False)

    titolo = "{}  ·  f0 {:.3f} MHz  ·  {}".format(nome.strip(), f0 / 1e6, riferimento)
    if p.dates:
        titolo += "\n{:%Y-%m-%d}  ·  elevazione max {:.0f}°".format(p.dates[0], max(p.elevs))
    ax.set_title(titolo, fontsize=10)

    # Frequenza da sintonizzare in ricezione: f0 + Δf
    f0_mhz = f0 / 1e6
    ax_f = ax.secondary_yaxis('right', functions=(lambda khz: f0_mhz + khz / 1000., lambda mhz: (mhz - f0_mhz) * 1000.))
    ax_f.set_ylabel("Frequenza da sintonizzare [MHz]")
    ax_f.yaxis.set_major_formatter(FormatStrFormatter('%.4f'))

    ax_el.plot(p.dates, p.elevs, color='k')
    ax_el.axhline(min_elev, color='gray', linestyle='--', linewidth=1)
    ax_el.axhspan(0, min_elev, color='gray', alpha=0.15, linewidth=0)
    ax_el.set_ylim(bottom=0)
    ax_el.set_xlabel("UTC")
    ax_el.set_ylabel("Elevazione [°]")
    ax_el.grid(True, linestyle=':')
    # Equivalente di fig.autofmt_xdate(), che non ruota le etichette se nella figura ci sono i widget
    plt.setp(ax_el.get_xticklabels(), rotation=30, ha='right')


def parse_args():
    parser = argparse.ArgumentParser(description="Traccia il satellite e calcola il prossimo passaggio")
    parser.add_argument("-f", "--freq", type=float, default=F0_DEFAULT_MHZ, metavar="MHZ",
                        help="frequenza di downlink per la curva Doppler, in MHz (default %(default).3f)")
    args = parser.parse_args()
    if args.freq <= 0:
        parser.error("la frequenza deve essere positiva")
    return args


def main():
    args = parse_args()

    tle = load_tle()
    print("TLE: {} (epoca {:%Y-%m-%d %H:%M} UTC)".format(tle.name, tle.epoch.datetime))

    station = create_station('KSC', KSC)
    riferimento = "{} ({:.2f}°{}, {:.2f}°{})".format(
        station.name, abs(KSC[0]), 'N' if KSC[0] >= 0 else 'S', abs(KSC[1]), 'E' if KSC[1] >= 0 else 'O')

    sun = get_body('Sun')
    start = Date.now()

    # Stato modificabile dai widget: il passaggio mostrato e la frequenza di downlink
    stato = {'p': find_pass(tle, station, sun, start), 'f0': args.freq * 1e6}
    stampa_passaggio(stato['p'], tle.name, stato['f0'], riferimento)

    orb = tle.orbit()
    longitudes, latitudes, orbit_pts = ground_track(orb, start)

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

    fig_map, ax_map = plt.subplots(figsize=(15.2, 8.2))
    plot_map(ax_map, longitudes, latitudes, lon, lat)
    # Traccia del passaggio mostrato e marker del cursore: la mappa non viene mai pulita, si aggiornano con set_data
    traccia_pass, = ax_map.plot([], [], color='tab:orange', linewidth=2)
    marker_map, = ax_map.plot([], [], 'o', color='tab:orange', markeredgecolor='k', markersize=10, visible=False)
    fig_map.tight_layout()

    fig_pol, ax_pol = plt.subplots(subplot_kw={'projection': 'polar'})

    fig, (ax, ax_el) = plt.subplots(2, 1, sharex=True, figsize=(7, 6.6), height_ratios=[2, 1], layout='constrained')
    # Il layout usa solo la parte sopra il 9% in basso; lì vanno i widget, che il layout ignora
    fig.get_layout_engine().set(rect=(0, 0.09, 1, 0.91))
    box = TextBox(fig.add_axes([0.17, 0.02, 0.2, 0.05]), "f0 [MHz] ", initial="{:.3f}".format(args.freq))
    btn = Button(fig.add_axes([0.55, 0.02, 0.35, 0.05]), "Passaggio successivo")

    cursore = {}

    def ridisegna():
        p = stato['p']
        plot_polar(ax_pol, p)
        plot_doppler(ax, ax_el, p, stato['f0'], tle.name, riferimento)

        # Interrompe la traccia dove attraversa l'antimeridiano
        lons, lats = np.array(p.lons), np.array(p.lats)
        salti = np.where(np.abs(np.diff(lons)) > 180)[0] + 1
        traccia_pass.set_data(np.insert(lons, salti, np.nan), np.insert(lats, salti, np.nan))

        # clear() ha rimosso i marker del cursore da polare e Doppler: vanno ricreati
        cursore['t'] = mdates.date2num(p.dates)
        cursore['i'] = None
        # Nasce sul primo campione: una x fuori dai dati allargherebbe l'autoscale dell'asse dei tempi
        x0 = p.dates[0] if p.dates else 0
        cursore['linee'] = [a.axvline(x0, color='tab:orange', linewidth=1, visible=False) for a in (ax, ax_el)]
        cursore['polare'], = ax_pol.plot([], [], 'o', color='tab:orange', markeredgecolor='k', markersize=10, visible=False)
        marker_map.set_visible(False)

        fig_pol.canvas.draw_idle()
        fig.canvas.draw_idle()
        fig_map.canvas.draw_idle()

    def sposta_cursore(i):
        """Porta i marker al campione i del passaggio, oppure li nasconde se i è None."""
        if i == cursore['i']:
            return
        cursore['i'] = i
        artisti = cursore['linee'] + [cursore['polare'], marker_map]
        for artista in artisti:
            artista.set_visible(i is not None)
        if i is not None:
            p = stato['p']
            for linea in cursore['linee']:
                linea.set_xdata([p.dates[i]] * 2)
            cursore['polare'].set_data([np.radians(p.azims[i])], [90 - p.elevs[i]])
            marker_map.set_data([p.lons[i]], [p.lats[i]])
        for f in (fig, fig_pol, fig_map):
            f.canvas.draw_idle()

    def on_move(event):
        if event.inaxes in (ax, ax_el) and len(cursore['t']):
            sposta_cursore(int(np.argmin(np.abs(cursore['t'] - event.xdata))))
        else:
            sposta_cursore(None)

    def on_freq(testo):
        try:
            f0 = float(testo.replace(',', '.')) * 1e6
        except ValueError:
            f0 = 0
        if f0 <= 0:
            print("Frequenza non valida: {!r}".format(testo))
            box.set_val("{:.3f}".format(stato['f0'] / 1e6))
            return
        if f0 != stato['f0']:
            stato['f0'] = f0
            ridisegna()

    def on_next(_):
        p = stato['p']
        if not p.trovato:
            print("Nessun passaggio successivo da cercare")
            return
        btn.label.set_text("Calcolo...")
        fig.canvas.draw()
        fig.canvas.flush_events()
        stato['p'] = find_pass(tle, station, sun, p.evento("LOS")[0] + timedelta(minutes=1))
        stampa_passaggio(stato['p'], tle.name, stato['f0'], riferimento)
        btn.label.set_text("Passaggio successivo")
        ridisegna()

    box.on_submit(on_freq)
    btn.on_clicked(on_next)
    fig.canvas.mpl_connect('motion_notify_event', on_move)
    fig.canvas.mpl_connect('figure_leave_event', lambda _: sposta_cursore(None))

    ridisegna()
    plt.show()


if __name__ == "__main__":
    main()
