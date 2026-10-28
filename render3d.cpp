#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

static const double R_TERRA = 6378.137;
static const std::string ORBIT_IN = "orbit3d.txt";
static const std::string IMG = "images/terra2.jpg";
static const std::string IMG_NOTTE = "images/terra_noc.jpg";
static const std::string OUT = "render3d.html";

struct Vec3 { double x, y, z; };

using Intervalli = std::vector<std::pair<double, double>>;

// Contenuto di orbit3d.txt: tempi in secondi da t0, posizioni ITRF in km
struct Timeline {
    std::string name, t0;
    double passo = 0, periodo = 0, durata = 0;
    Vec3 ksc{};
    Intervalli sopra, visibile;
    std::vector<Vec3> sat, sole;
};

static std::string readFile(const std::string& path)
{
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("impossibile aprire " + path);
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static std::runtime_error malformata(const std::string& line)
{
    return std::runtime_error("riga malformata in " + ORBIT_IN + ": " + line +
                              "\n(se il file viene da una versione precedente, rigeneralo con python3 astro.py)");
}

// Legge esattamente n numeri dalla riga
static std::vector<double> parseNums(const std::string& line, size_t n)
{
    std::istringstream in(line);
    std::vector<double> v(n);
    for (double& x : v)
        if (!(in >> x)) throw malformata(line);
    std::string extra;
    if (in >> extra) throw malformata(line);
    return v;
}

static Timeline readTimeline(const std::string& path)
{
    std::istringstream in(readFile(path));
    std::vector<std::string> lines;
    for (std::string line; std::getline(in, line);)
        if (line.find_first_not_of(" \t\r") != std::string::npos) lines.push_back(line);
    size_t k = 0;
    auto next = [&]() -> const std::string& {
        if (k >= lines.size()) throw std::runtime_error(path + " incompleto");
        return lines[k++];
    };

    Timeline tl;
    tl.name = next();

    const std::string& header = next();
    std::istringstream h(header);
    std::string extra;
    if (!(h >> tl.t0 >> tl.passo >> tl.periodo >> tl.durata) || (h >> extra) || tl.passo <= 0)
        throw malformata(header);

    auto v = parseNums(next(), 3);
    tl.ksc = {v[0], v[1], v[2]};

    for (Intervalli* intervalli : {&tl.sopra, &tl.visibile}) {
        size_t n = (size_t)parseNums(next(), 1)[0];
        for (size_t i = 0; i < n; ++i) {
            v = parseNums(next(), 2);
            intervalli->push_back({v[0], v[1]});
        }
    }

    while (k < lines.size()) {
        v = parseNums(lines[k++], 6);
        tl.sat.push_back({v[0], v[1], v[2]});
        tl.sole.push_back({v[3], v[4], v[5]});
    }
    if (tl.sat.size() < 2) throw std::runtime_error(path + " contiene meno di due campioni");
    return tl;
}

static std::string base64(const std::string& in)
{
    static const char* tab = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    out.reserve((in.size() + 2) / 3 * 4);
    for (size_t i = 0; i < in.size(); i += 3) {
        unsigned v = (unsigned char)in[i] << 16;
        if (i + 1 < in.size()) v |= (unsigned char)in[i + 1] << 8;
        if (i + 2 < in.size()) v |= (unsigned char)in[i + 2];
        out += tab[(v >> 18) & 63];
        out += tab[(v >> 12) & 63];
        out += i + 1 < in.size() ? tab[(v >> 6) & 63] : '=';
        out += i + 2 < in.size() ? tab[v & 63] : '=';
    }
    return out;
}

static std::ostream& operator<<(std::ostream& f, const Vec3& v)
{
    return f << '[' << v.x << ',' << v.y << ',' << v.z << ']';
}

static void writeArray(std::ostream& f, const std::vector<Vec3>& v)
{
    f << '[';
    for (size_t i = 0; i < v.size(); ++i) f << (i ? "," : "") << v[i];
    f << ']';
}

static void writeArray(std::ostream& f, const Intervalli& v)
{
    f << '[';
    for (size_t i = 0; i < v.size(); ++i) f << (i ? "," : "") << '[' << v[i].first << ',' << v[i].second << ']';
    f << ']';
}

static void writeRender3D(const std::string& path, const std::string& img, const std::string& imgNotte,
                          const Timeline& tl)
{
    std::ofstream f(path);
    f.setf(std::ios::fixed);
    f.precision(3);
    f << R"HTML(<!doctype html>
<html><head><meta charset='utf-8'><title>Render 3D</title>
<style>
body { margin: 0; background: black; overflow: hidden; font-family: sans-serif; color: white; }
#legend { position: absolute; top: 12px; right: 12px; padding: 8px 12px; border: 1px solid #666; background: rgba(0,0,0,.7); font-size: 14px; line-height: 1.6; }
#legend span { display: inline-block; width: 22px; margin-right: 6px; text-align: center; }
#hint { position: absolute; top: 12px; left: 12px; font-size: 12px; color: #888; }
#controlli { position: absolute; left: 12px; right: 12px; bottom: 12px; display: flex; align-items: center; gap: 10px;
             padding: 6px 10px; border: 1px solid #666; background: rgba(0,0,0,.7); font-size: 14px; }
#controlli button, #controlli select { height: 28px; background: #222; color: white; border: 1px solid #666; border-radius: 4px; font-size: 14px; cursor: pointer; }
#controlli button { width: 34px; }
#barra { position: relative; flex: 1; height: 22px; }
/* Passaggi sotto lo slider; 7px = mezzo cursore, così le barre coincidono con la corsa del cursore */
#passi { position: absolute; left: 7px; right: 7px; top: 8px; height: 6px; border-radius: 3px; background: rgba(255,255,255,.15); }
#passi span { position: absolute; top: 0; height: 100%; min-width: 2px; background: #999; }
#passi span.vis { background: #33dd66; }
#barra input { position: absolute; inset: 0; width: 100%; height: 22px; margin: 0; -webkit-appearance: none; appearance: none; background: transparent; cursor: pointer; }
#barra input::-webkit-slider-runnable-track { height: 22px; background: transparent; }
#barra input::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; margin-top: 4px; border-radius: 50%; background: white; }
#barra input::-moz-range-track { height: 22px; background: transparent; }
#barra input::-moz-range-thumb { width: 14px; height: 14px; border: 0; border-radius: 50%; background: white; }
#ora { font-variant-numeric: tabular-nums; white-space: nowrap; }
#stato { min-width: 13em; white-space: nowrap; color: #bbb; }
</style>
<script type='importmap'>{"imports": {
  "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
  "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
}}</script>
</head><body>
<div id='legend'>
<div><span>&middot;&middot;&middot;</span>Orbita (1 periodo in avanti)</div>
<div><span style='color:red'>&#9679;</span>)HTML" << tl.name << R"HTML(</div>
<div><span style='color:yellow'>&#9679;</span>KSC</div>
<div><span style='color:#4466aa'>&#9608;</span>Ombra della Terra</div>
<div><span style='color:#999'>&#9473;</span>Sopra l'orizzonte di KSC</div>
<div><span style='color:#33dd66'>&#9473;</span>Visibile a occhio nudo</div>
</div>
<div id='hint'>Trascina -> ruotare, Rotella -> zoom</div>
<div id='controlli'>
<button id='play' title='Play / Pausa'>&#9654;</button>
<button id='stop' title='Stop: torna all&rsquo;inizio'>&#9632;</button>
<div id='barra'><div id='passi'></div><input id='slider' type='range' min='0' step='any' value='0'></div>
<span id='ora'></span>
<span id='stato'></span>
<select id='velocita' title='Velocit&agrave; della simulazione'>
<option value='60'>&times;60</option><option value='300' selected>&times;300</option>
<option value='1000'>&times;1000</option><option value='3000'>&times;3000</option>
</select>
</div>
<script type='module'>
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';

const R = )HTML" << R_TERRA << ";\n";
    f << "const t0 = Date.parse('" << tl.t0 << "'), passo = " << tl.passo << ", periodo = " << tl.periodo
      << ", durata = " << tl.durata << ";\n";
    f << "const ksc = " << tl.ksc << ";\n";
    f.precision(1);
    f << "const sopra = ";
    writeArray(f, tl.sopra);
    f << ", visibile = ";
    writeArray(f, tl.visibile);
    f << ";\n";
    f.precision(3);
    f << "const sat = ";
    writeArray(f, tl.sat);
    f << ";\n";
    f.precision(6);
    f << "const sole = ";
    writeArray(f, tl.sole);
    f << ";\n";
    f.precision(3);
    f << "const tex = 'data:image/jpeg;base64," << base64(readFile(img)) << "';\n";
    if (imgNotte.empty()) f << "const texNotte = null;\n";
    else f << "const texNotte = 'data:image/jpeg;base64," << base64(readFile(imgNotte)) << "';\n";
    f << R"HTML(
const VERDE = 0x33dd66, GRIGIO = 0x999999;

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, innerWidth / innerHeight, 100, 1e6);
camera.up.set(0, 0, 1);

// Interpolazione lineare normalizzata: la direzione segue l'arco tra due campioni e il modulo varia
// linearmente. Con campioni ogni 60 s l'errore sulla posizione è sotto il km, contro ~4 km della corda.
const va = new THREE.Vector3(), vb = new THREE.Vector3();
function interp(arr, t, out) {
    const x = THREE.MathUtils.clamp(t / passo, 0, arr.length - 1);
    const i = Math.min(Math.floor(x), arr.length - 2), f = x - i;
    va.fromArray(arr[i]);
    vb.fromArray(arr[i + 1]);
    const len = va.length() + (vb.length() - va.length()) * f;
    return out.lerpVectors(va, vb, f).setLength(len);
}
const dentro = (intervalli, t) => intervalli.some(([a, b]) => t >= a && t <= b);

const nLat = 90, nLon = 180, pos = [], uv = [], idx = [];
for (let i = 0; i <= nLat; i++) {
    const lat = Math.PI * (i / nLat - 0.5);
    for (let j = 0; j <= nLon; j++) {
        const lon = 2 * Math.PI * (j / nLon - 0.5);
        pos.push(R * Math.cos(lat) * Math.cos(lon), R * Math.cos(lat) * Math.sin(lon), R * Math.sin(lat));
        uv.push(j / nLon, i / nLat);
    }
}
for (let i = 0; i < nLat; i++)
    for (let j = 0; j < nLon; j++) {
        const a = i * (nLon + 1) + j, b = a + nLon + 1;
        idx.push(a, a + 1, b, b, a + 1, b + 1);
    }
const earthGeo = new THREE.BufferGeometry();
earthGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
earthGeo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
earthGeo.setIndex(idx);
function loadTex(src) {
    const t = new THREE.TextureLoader().load(src);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = renderer.capabilities.getMaxAnisotropy();
    return t;
}
// Unico vettore condiviso da shader e cilindro d'ombra: aggiorna() lo modifica sul posto
const sunDir = new THREE.Vector3().fromArray(sole[0]);
const dayMap = loadTex(tex);
scene.add(new THREE.Mesh(earthGeo, new THREE.ShaderMaterial({
    uniforms: {
        dayMap: { value: dayMap },
        nightMap: { value: texNotte ? loadTex(texNotte) : dayMap },
        nightGain: { value: texNotte ? 1.0 : 0.12 },
        sunDir: { value: sunDir },
    },
    vertexShader: `
        varying vec2 vUv;
        varying vec3 vNormal;
        void main() {
            vUv = uv;
            vNormal = normalize(position);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
    fragmentShader: `
        uniform sampler2D dayMap, nightMap;
        uniform float nightGain;
        uniform vec3 sunDir;
        varying vec2 vUv;
        varying vec3 vNormal;
        void main() {
            // sin(6 gradi) ~ 0.1: fascia di crepuscolo attorno al terminatore
            float giorno = smoothstep(-0.1, 0.1, dot(normalize(vNormal), sunDir));
            vec3 c = mix(texture2D(nightMap, vUv).rgb * nightGain, texture2D(dayMap, vUv).rgb, giorno);
            gl_FragColor = vec4(c, 1.0);
            #include <colorspace_fragment>
        }`,
})));

function addWithGhost(make) {
    const obj = make({}), ghost = make({ transparent: true, opacity: 0.25, depthTest: false });
    ghost.renderOrder = 1;
    scene.add(obj, ghost);
    return [obj, ghost];
}
const resolution = new THREE.Vector2(innerWidth, innerHeight);

// Orbita: un periodo in avanti dalla posizione attuale. La geometria si ricostruisce a ogni
// aggiornamento (circa 100 punti) e le due linee la condividono.
let orbitGeo = new LineGeometry();
const orbitLines = addWithGhost(opts => new Line2(orbitGeo, new LineMaterial({
    color: 'white', linewidth: opts.depthTest === false ? 1 : 2, dashed: true, dashSize: 150, gapSize: 250,
    resolution, ...opts })));
const tmp = new THREE.Vector3();
function setOrbita(t) {
    const pts = [...interp(sat, t, tmp).toArray()];
    for (let i = Math.floor(t / passo) + 1; i * passo < t + periodo && i < sat.length; i++) pts.push(...sat[i]);
    pts.push(...interp(sat, t + periodo, tmp).toArray());
    const g = new LineGeometry();
    g.setPositions(pts);
    for (const l of orbitLines) l.geometry = g;
    orbitLines[0].computeLineDistances();
    orbitGeo.dispose();
    orbitGeo = g;
}

const satMarkers = addWithGhost(opts =>
    new THREE.Mesh(new THREE.SphereGeometry(150, 16, 12), new THREE.MeshBasicMaterial({ color: 'red', ...opts })));
addWithGhost(opts => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(90, 16, 12), new THREE.MeshBasicMaterial({ color: 'yellow', ...opts }));
    m.position.set(...ksc);
    return m;
});

// Linea KSC -> satellite: un solo segmento, aggiornato sul posto nel buffer della geometria
const linkGeo = new LineGeometry();
linkGeo.setPositions([...ksc, ...ksc]);
const linkBuf = linkGeo.attributes.instanceStart.data;
const linkLines = addWithGhost(opts => {
    const l = new Line2(linkGeo, new LineMaterial({ color: GRIGIO, linewidth: 2, resolution, ...opts }));
    l.frustumCulled = false;   // la bounding sphere calcolata all'inizio non segue il satellite
    return l;
});

const lim = Math.max(R, ...sat.map(p => Math.hypot(...p))) * 1.05;

// Ombra come cilindro di raggio R in direzione anti-Sole: per un'orbita bassa
// la conicita' dell'umbra (~0.27 gradi) e' trascurabile. Parte a 0.05 R dal centro
// perche' sul terminatore la parete toccherebbe la sfera (z-fighting).
const shadowStart = 0.05 * R, shadowLen = lim * 3;
const shadow = new THREE.Mesh(
    new THREE.CylinderGeometry(R, R, shadowLen, 96, 1, true),
    new THREE.MeshBasicMaterial({ color: 0x223366, transparent: true, opacity: 0.3,
                                  side: THREE.DoubleSide, depthWrite: false }));
scene.add(shadow);
const asseY = new THREE.Vector3(0, 1, 0);

camera.position.set(...sat[0]).setLength(lim / Math.tan(THREE.MathUtils.degToRad(35 / 2)) * 1.1);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.minDistance = R * 1.3;
controls.maxDistance = lim * 10;

const slider = document.getElementById('slider'), btnPlay = document.getElementById('play');
const ora = document.getElementById('ora'), stato = document.getElementById('stato');
const velocita = document.getElementById('velocita');
slider.max = durata;

const passi = document.getElementById('passi');
for (const [lista, cls] of [[sopra, 'sopra'], [visibile, 'vis']])
    for (const [a, b] of lista) {
        if (a > durata) continue;
        const s = document.createElement('span');
        s.className = cls;
        s.style.left = 100 * a / durata + '%';
        s.style.width = 100 * (Math.min(b, durata) - a) / durata + '%';
        passi.appendChild(s);
    }

const satPos = new THREE.Vector3();
function aggiorna(t) {
    interp(sat, t, satPos);
    for (const m of satMarkers) m.position.copy(satPos);
    setOrbita(t);

    interp(sole, t, sunDir);
    shadow.quaternion.setFromUnitVectors(asseY, tmp.copy(sunDir).negate());
    shadow.position.copy(sunDir).multiplyScalar(-(shadowStart + shadowLen / 2));

    const su = dentro(sopra, t), vis = su && dentro(visibile, t);
    for (const l of linkLines) {
        l.visible = su;
        l.material.color.set(vis ? VERDE : GRIGIO);
    }
    if (su) {
        linkBuf.array.set(satPos.toArray(), 3);
        linkBuf.needsUpdate = true;
    }

    slider.value = t;
    ora.textContent = new Date(t0 + t * 1000).toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
    stato.textContent = vis ? 'visibile a occhio nudo da KSC' : su ? "sopra l'orizzonte di KSC" : '';
    stato.style.color = vis ? '#33dd66' : '';
}

let t = 0, inMoto = false, ultimo = 0;
function setInMoto(v) {
    inMoto = v;
    btnPlay.innerHTML = v ? '&#10074;&#10074;' : '&#9654;';
}
btnPlay.addEventListener('click', () => {
    if (!inMoto && t >= durata) aggiorna(t = 0);
    setInMoto(!inMoto);
});
document.getElementById('stop').addEventListener('click', () => {
    setInMoto(false);
    aggiorna(t = 0);
});
slider.addEventListener('input', () => aggiorna(t = +slider.value));

addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
    scene.traverse(o => o.material?.resolution?.set(innerWidth, innerHeight));
});
renderer.setAnimationLoop(ms => {
    if (inMoto) {
        // Limita il passo: con la scheda in background il browser sospende il loop
        const dt = Math.min((ms - ultimo) / 1000, 0.1);
        t = Math.min(t + dt * velocita.value, durata);
        if (t >= durata) setInMoto(false);
        aggiorna(t);
    }
    ultimo = ms;
    controls.update();
    renderer.render(scene, camera);
});
aggiorna(0);
</script>
</body></html>
)HTML";
}

int main()
{
    try {
        Timeline tl = readTimeline(ORBIT_IN);
        std::string imgNotte = std::ifstream(IMG_NOTTE) ? IMG_NOTTE : "";
        if (imgNotte.empty()) std::cout << IMG_NOTTE << " non trovato, lato notte = texture diurna scurita\n";
        writeRender3D(OUT, IMG, imgNotte, tl);
        std::cout << "Scritto " << OUT << " (" << tl.sat.size() << " campioni, " << tl.sopra.size()
                  << " passaggi sopra l'orizzonte)\n";
    } catch (const std::exception& e) {
        std::cerr << "Errore: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
