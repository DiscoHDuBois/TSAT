#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

static const double R_TERRA = 6378.137;
static const std::string ORBIT_IN = "orbit3d.txt";
static const std::string IMG = "images/terra2.jpg";
static const std::string IMG_NOTTE = "images/terra_noc.jpg";
static const std::string OUT = "render3d.html";

struct Vec3 { double x, y, z; };

static std::string readFile(const std::string& path)
{
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("impossibile aprire " + path);
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static Vec3 parseVec(const std::string& line)
{
    std::istringstream in(line);
    Vec3 v;
    if (!(in >> v.x >> v.y >> v.z)) throw std::runtime_error("riga malformata in " + ORBIT_IN + ": " + line);
    return v;
}

static void readOrbit(const std::string& path, std::string& name, Vec3& sat, Vec3& ksc, Vec3& sun,
                      std::vector<Vec3>& orbit)
{
    std::istringstream in(readFile(path));
    std::string line;
    if (!std::getline(in, name)) throw std::runtime_error(path + " vuoto");
    if (!std::getline(in, line)) throw std::runtime_error(path + " incompleto");
    sat = parseVec(line);
    if (!std::getline(in, line)) throw std::runtime_error(path + " incompleto");
    ksc = parseVec(line);
    if (!std::getline(in, line)) throw std::runtime_error(path + " incompleto");
    sun = parseVec(line);
    while (std::getline(in, line))
        if (line.find_first_not_of(" \t\r") != std::string::npos) orbit.push_back(parseVec(line));
    if (orbit.empty()) throw std::runtime_error(path + " non contiene punti dell'orbita");
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

static void writeRender3D(const std::string& path, const std::string& img, const std::string& imgNotte,
                          const std::string& name, const std::vector<Vec3>& orbit, Vec3 sat, Vec3 ksc, Vec3 sun)
{
    std::ofstream f(path);
    f.setf(std::ios::fixed);
    f.precision(3);
    f << R"(<!doctype html>
<html><head><meta charset='utf-8'><title>Render 3D</title>
<style>
body { margin: 0; background: black; overflow: hidden; font-family: sans-serif; color: white; }
#legend { position: absolute; top: 12px; right: 12px; padding: 8px 12px; border: 1px solid #666; background: rgba(0,0,0,.7); font-size: 14px; line-height: 1.6; }
#legend span { display: inline-block; width: 22px; margin-right: 6px; text-align: center; }
#hint { position: absolute; bottom: 10px; left: 12px; font-size: 12px; color: #888; }
</style>
<script type='importmap'>{"imports": {
  "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
  "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
}}</script>
</head><body>
<div id='legend'>
<div><span>&middot;&middot;&middot;</span>Orbita (1 periodo)</div>
<div><span style='color:red'>&#9679;</span>)" << name << R"(</div>
<div><span style='color:yellow'>&#9679;</span>KSC</div>
<div><span style='color:#4466aa'>&#9608;</span>Ombra della Terra</div>
</div>
<div id='hint'>Trascina -> ruotare, Rotella -> zoom</div>
<script type='module'>
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';

const R = )" << R_TERRA << ";\nconst orbit = [";
    for (size_t i = 0; i < orbit.size(); ++i) f << (i ? "," : "") << orbit[i];
    f << "];\nconst sat = " << sat << ", ksc = " << ksc << ";\n";
    f.precision(6);
    f << "const sunDir = new THREE.Vector3(..." << sun << ").normalize();\n";
    f.precision(3);
    f << "const tex = 'data:image/jpeg;base64," << base64(readFile(img)) << "';\n";
    if (imgNotte.empty()) f << "const texNotte = null;\n";
    else f << "const texNotte = 'data:image/jpeg;base64," << base64(readFile(imgNotte)) << "';\n";
    f << R"(
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, innerWidth / innerHeight, 100, 1e6);
camera.up.set(0, 0, 1);

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
    const ghost = make({ transparent: true, opacity: 0.25, depthTest: false });
    ghost.renderOrder = 1;
    scene.add(make({}), ghost);
}

const lineGeo = new LineGeometry();
lineGeo.setPositions(orbit.flat());
addWithGhost(opts => {
    const line = new Line2(lineGeo, new LineMaterial({
        color: 'white', linewidth: opts.depthTest === false ? 1 : 2, dashed: true, dashSize: 150, gapSize: 250,
        resolution: new THREE.Vector2(innerWidth, innerHeight), ...opts }));
    line.computeLineDistances();
    return line;
});
for (const [p, color, r] of [[sat, 'red', 150], [ksc, 'yellow', 90]])
    addWithGhost(opts => {
        const m = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12), new THREE.MeshBasicMaterial({ color, ...opts }));
        m.position.set(...p);
        return m;
    });

const lim = Math.max(R, ...orbit.map(p => Math.hypot(...p))) * 1.05;

// Ombra come cilindro di raggio R in direzione anti-Sole: per un'orbita bassa
// la conicita' dell'umbra (~0.27 gradi) e' trascurabile. Parte a 0.05 R dal centro
// perche' sul terminatore la parete toccherebbe la sfera (z-fighting).
const shadowStart = 0.05 * R, shadowLen = lim * 3;
const shadow = new THREE.Mesh(
    new THREE.CylinderGeometry(R, R, shadowLen, 96, 1, true),
    new THREE.MeshBasicMaterial({ color: 0x223366, transparent: true, opacity: 0.3,
                                  side: THREE.DoubleSide, depthWrite: false }));
shadow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), sunDir.clone().negate());
shadow.position.copy(sunDir).multiplyScalar(-(shadowStart + shadowLen / 2));
scene.add(shadow);
camera.position.set(...sat).setLength(lim / Math.tan(THREE.MathUtils.degToRad(35 / 2)) * 1.1);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.minDistance = R * 1.3;
controls.maxDistance = lim * 10;

addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
    scene.traverse(o => o.material?.resolution?.set(innerWidth, innerHeight));
});
renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
</script>
</body></html>
)";
}

int main()
{
    try {
        std::string name;
        Vec3 sat, ksc, sun;
        std::vector<Vec3> orbit;
        readOrbit(ORBIT_IN, name, sat, ksc, sun, orbit);
        std::string imgNotte = std::ifstream(IMG_NOTTE) ? IMG_NOTTE : "";
        if (imgNotte.empty()) std::cout << IMG_NOTTE << " non trovato, lato notte = texture diurna scurita\n";
        writeRender3D(OUT, IMG, imgNotte, name, orbit, sat, ksc, sun);
        std::cout << "Scritto " << OUT << " (" << orbit.size() << " punti)\n";
    } catch (const std::exception& e) {
        std::cerr << "Errore: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
