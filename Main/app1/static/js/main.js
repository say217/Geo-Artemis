/* ═══════════════════════════════════════════
   NAV STUCK
═══════════════════════════════════════════ */
window.addEventListener('scroll',()=>document.getElementById('main-nav').classList.toggle('stuck',scrollY>60));

/* ═══════════════════════════════════════════
   UNIVERSAL REVEAL OBSERVER
   Handles: .reveal, .pipe-card, .hz-card, .bento, .intel-feat, .stat-cell
═══════════════════════════════════════════ */
const revealTargets = '.reveal, .pipe-card, .hz-card, .bento, .intel-feat, .stat-cell';
const ro = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      e.target.classList.add('in');
      ro.unobserve(e.target);
    }
  });
}, { threshold: 0.07 });
document.querySelectorAll(revealTargets).forEach(el => ro.observe(el));

/* ═══════════════════════════════════════════
   GLOBE SECTION REVEAL
═══════════════════════════════════════════ */
const globeObserver = new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting) {
    document.getElementById('globe-wrap').classList.add('globe-in');
    document.getElementById('globe-text').classList.add('globe-in');
    globeObserver.disconnect();
  }
}, { threshold: 0.12 });
globeObserver.observe(document.getElementById('globe-section'));

/* ═══════════════════════════════════════════
   3D GLOBE — Three.js
═══════════════════════════════════════════ */
(function initGlobe() {
  const canvas = document.getElementById('globe-three-canvas');
  const wrap = document.getElementById('globe-wrap');

  const scene = new THREE.Scene();
  const W = () => wrap.clientWidth;
  const H = () => wrap.clientHeight;

  const camera = new THREE.PerspectiveCamera(55, W() / H(), 0.1, 1000);
  camera.position.z = 14;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(W(), H());
  renderer.setClearColor(0x000000, 0);

  // Earth
  const geo = new THREE.SphereGeometry(6.5, 96, 96);
  const loader = new THREE.TextureLoader();
  const earthTex = loader.load('https://unpkg.com/three-globe@2.31.0/example/img/earth-blue-marble.jpg');
  const bumpTex  = loader.load('https://unpkg.com/three-globe@2.31.0/example/img/earth-topology.png');

  const mat = new THREE.MeshPhongMaterial({
    map: earthTex,
    bumpMap: bumpTex,
    bumpScale: 0.05,
    shininess: 10,
    specular: new THREE.Color(0x111111)
  });
  const earth = new THREE.Mesh(geo, mat);
  scene.add(earth);

  // Atmosphere glow shell
  const atmGeo = new THREE.SphereGeometry(6.72, 64, 64);
  const atmMat = new THREE.MeshPhongMaterial({
    color: 0x06e5ff,
    transparent: true,
    opacity: 0.04,
    side: THREE.FrontSide,
    depthWrite: false
  });
  scene.add(new THREE.Mesh(atmGeo, atmMat));

  // Lights
  scene.add(new THREE.AmbientLight(0x223344, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(14, 6, 10);
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0x3b5bff, 0.25);
  fill.position.set(-10, -4, -8);
  scene.add(fill);

  // Stars
  const starsGeo = new THREE.BufferGeometry();
  const N = 12000;
  const pos = new Float32Array(N * 3);
  const col = new Float32Array(N * 3);
  for (let i = 0; i < N * 3; i += 3) {
    const r = 280, t = Math.random() * Math.PI * 2, p = Math.acos(2 * Math.random() - 1);
    pos[i]   = r * Math.sin(p) * Math.cos(t);
    pos[i+1] = r * Math.sin(p) * Math.sin(t);
    pos[i+2] = r * Math.cos(p);
    const b = 0.75 + Math.random() * 0.25;
    col[i] = b; col[i+1] = b; col[i+2] = b;
  }
  starsGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  starsGeo.setAttribute('color',    new THREE.BufferAttribute(col, 3));
  scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({ size: 0.6, vertexColors: true, transparent: true, opacity: 0.85 })));

  // Interaction
  let dragging = false, prevX = 0, prevY = 0;
  canvas.addEventListener('mousedown', e => { dragging = true; prevX = e.clientX; prevY = e.clientY; });
  window.addEventListener('mouseup', () => { dragging = false; });
  canvas.addEventListener('mousemove', e => {
    if (!dragging) return;
    earth.rotation.y += (e.clientX - prevX) * 0.005;
    earth.rotation.x = Math.max(-Math.PI/2, Math.min(Math.PI/2, earth.rotation.x + (e.clientY - prevY) * 0.005));
    prevX = e.clientX; prevY = e.clientY;
  });
  // Touch
  let lastTouch = null;
  canvas.addEventListener('touchstart', e => { lastTouch = e.touches[0]; });
  canvas.addEventListener('touchmove', e => {
    if (!lastTouch) return;
    const t = e.touches[0];
    earth.rotation.y += (t.clientX - lastTouch.clientX) * 0.005;
    earth.rotation.x = Math.max(-Math.PI/2, Math.min(Math.PI/2, earth.rotation.x + (t.clientY - lastTouch.clientY) * 0.005));
    lastTouch = t;
  });
  canvas.addEventListener('wheel', e => {
    camera.position.z = Math.max(9, Math.min(28, camera.position.z + e.deltaY * 0.018));
  }, { passive: true });

  // Resize
  window.addEventListener('resize', () => {
    camera.aspect = W() / H();
    camera.updateProjectionMatrix();
    renderer.setSize(W(), H());
  });

  // Animate
  (function animate() {
    requestAnimationFrame(animate);
    if (!dragging) earth.rotation.y += 0.0012;
    renderer.render(scene, camera);
  })();
})();

/* ═══════════════════════════════════════════
   STAT COUNTERS
═══════════════════════════════════════════ */
function countUp(el, end, sfx, dur = 1800) {
  let t0 = null;
  (function run(ts) {
    if (!t0) t0 = ts;
    const p = Math.min((ts - t0) / dur, 1);
    const v = Math.round(p * end);
    el.innerHTML = v.toLocaleString() + (sfx ? `<span class="stat-u">${sfx}</span>` : '');
    if (p < 1) requestAnimationFrame(run);
  })(performance.now());
}
const co = new IntersectionObserver(es => {
  if (es[0].isIntersecting) {
    countUp(document.getElementById('s1'), 847, '');
    countUp(document.getElementById('s2'), 1204, '');
    countUp(document.getElementById('s3'), 23, '');
    countUp(document.getElementById('s4'), 14, 'k+');
    co.disconnect();
  }
}, { threshold: .3 });
co.observe(document.querySelector('.stats-banner'));

/* ═══════════════════════════════════════════
   PARTICLE CANVAS BACKGROUND
═══════════════════════════════════════════ */
(function() {
  const c = document.createElement('canvas');
  c.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:0;opacity:0.6';
  document.body.appendChild(c);
  const ctx = c.getContext('2d');
  let W, H, nodes = [];
  function resize() {
    W = c.width = innerWidth;
    H = c.height = innerHeight;
    nodes = Array.from({ length: 70 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - .5) * .22, vy: (Math.random() - .5) * .16,
      r: Math.random() * 1.1 + .2
    }));
  }
  window.addEventListener('resize', resize); resize();
  function draw() {
    ctx.clearRect(0, 0, W, H);
    nodes.forEach(n => {
      n.x += n.vx; n.y += n.vy;
      if (n.x < 0 || n.x > W) n.vx *= -1;
      if (n.y < 0 || n.y > H) n.vy *= -1;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(6,229,255,.15)'; ctx.fill();
    });
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < 130) {
          ctx.beginPath(); ctx.moveTo(nodes[i].x, nodes[i].y); ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.strokeStyle = `rgba(6,229,255,${.05 * (1 - d / 130)})`; ctx.lineWidth = .5; ctx.stroke();
        }
      }
    }
    requestAnimationFrame(draw);
  }
  draw();
})();

/* ═══════════════════════════════════════════
   LEAFLET CYBER MAP
═══════════════════════════════════════════ */
const mapEl = document.getElementById('cyber-map');
if (mapEl) {
  const cyberMap = L.map('cyber-map', { zoomControl: false, attributionControl: false }).setView([5, 0], 2);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(cyberMap);
  const hazardIcon = (label) => L.divIcon({
    className: '',
    html: `<div class="hazard-tag">${label}</div>`,
    iconSize: [140, 20], iconAnchor: [10, 10]
  });
  [
    { label: 'Tropical Cyclone Maila', lat: -9.1, lon: 155.1 },
    { label: 'Tropical Cyclone Indusa', lat: -19.1, lon: 70.5 },
    { label: 'Julie Pond Wildfire', lat: 38.396085, lon: -75.97625 },
    { label: 'Rx Prescribed Fire', lat: 45.7153853, lon: -92.6888328 },
    { label: 'Hall Thompson Lane Wildfire', lat: 33.4077778, lon: -86.5408333 }
  ].forEach(h => L.marker([h.lat, h.lon], { icon: hazardIcon(h.label) }).addTo(cyberMap));
}

/* ═══════════════════════════════════════════
   FEAT-LINE HOVER (operational excellence)
═══════════════════════════════════════════ */
document.querySelectorAll('.feat-line').forEach(el => {
  el.addEventListener('mouseenter', () => el.style.color = '#dce4ff');
  el.addEventListener('mouseleave', () => el.style.color = '');
});
