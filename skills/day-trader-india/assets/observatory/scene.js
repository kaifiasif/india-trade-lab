// Three.js scenes for the observatory. Pure presentation: they draw recorded events and
// prices from /api/state and never call the API, change state or invent activity.
import * as THREE from "./vendor/three.module.min.js";

const BRAND = {
    purple: 0x7760ce,
    violet: 0x9a80cd,
    lavender: 0xd9cff3,
    mist: 0xf0ecfb,
    edge: 0xb5a0df,
    green: 0x358977,
    red: 0xbb5a65,
    ink: 0x252532,
};
const reducedMotion = () =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export function webglAvailable() {
    try {
        const canvas = document.createElement("canvas");
        return Boolean(
            window.WebGLRenderingContext &&
                (canvas.getContext("webgl2") || canvas.getContext("webgl")),
        );
    } catch {
        return false;
    }
}

function dotTexture() {
    const size = 512,
        canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d");
    for (let x = 8; x < size; x += 22)
        for (let y = 8; y < size; y += 22) {
            const d = Math.hypot(x - size / 2, y - size / 2) / (size / 2);
            ctx.fillStyle = `rgba(150, 128, 205, ${0.55 * Math.max(0, 1 - d * d)})`;
            ctx.beginPath();
            ctx.arc(x, y, 1.6, 0, Math.PI * 2);
            ctx.fill();
        }
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
}

// Shared renderer lifecycle: render on demand, animate only while something moves,
// pause when off screen or in a hidden tab, and follow the host's size.
class BaseScene {
    constructor(host, { fov = 38 } = {}) {
        this.host = host;
        this.renderer = new THREE.WebGLRenderer({
            antialias: true,
            alpha: true,
            powerPreference: "low-power",
        });
        this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
        this.renderer.setClearColor(0x000000, 0);
        this.canvas = this.renderer.domElement;
        this.canvas.setAttribute("aria-hidden", "true");
        host.prepend(this.canvas);
        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(fov, 1, 0.1, 100);
        this.target = new THREE.Vector3();
        this.yaw = 0;
        this.pitch = 0;
        this.baseYaw = 0;
        this.basePitch = 0;
        this.distance = 9;
        this.visible = true;
        this.frame = null;
        this.last = performance.now();
        this.scene.add(new THREE.HemisphereLight(0xffffff, 0xe6defa, 2.1));
        const sun = new THREE.DirectionalLight(0xffffff, 1.6);
        sun.position.set(3, 7, 5);
        this.scene.add(sun);
        this.resizeObserver = new ResizeObserver(() => this.resize());
        this.resizeObserver.observe(host);
        this.intersection = new IntersectionObserver(([entry]) => {
            this.visible = entry.isIntersecting;
            if (this.visible) this.kick();
        });
        this.intersection.observe(host);
        document.addEventListener("visibilitychange", () => this.kick());
        this.bindDrag();
        this.resize();
    }
    bindDrag() {
        let start = null;
        this.canvas.addEventListener("pointerdown", (event) => {
            start = {
                x: event.clientX,
                y: event.clientY,
                yaw: this.yaw,
                pitch: this.pitch,
                moved: false,
            };
            this.canvas.setPointerCapture(event.pointerId);
        });
        this.canvas.addEventListener("pointermove", (event) => {
            if (!start) return this.hover?.(event);
            const dx = event.clientX - start.x,
                dy = event.clientY - start.y;
            if (Math.abs(dx) + Math.abs(dy) > 4) start.moved = true;
            this.yaw = clamp(start.yaw - dx * 0.006, -0.75, 0.75);
            this.pitch = clamp(start.pitch + dy * 0.004, -0.25, 0.35);
            this.kick();
        });
        const end = (event) => {
            if (start && !start.moved) this.click?.(event);
            start = null;
        };
        this.canvas.addEventListener("pointerup", end);
        this.canvas.addEventListener("pointercancel", () => (start = null));
        this.canvas.addEventListener("pointerleave", () => this.leave?.());
        this.canvas.addEventListener("dblclick", () => {
            this.yaw = 0;
            this.pitch = 0;
            this.kick();
        });
    }
    placeCamera() {
        const yaw = this.baseYaw + this.yaw,
            pitch = this.basePitch + this.pitch;
        this.camera.position.set(
            this.target.x + this.distance * Math.sin(yaw) * Math.cos(pitch),
            this.target.y + this.distance * Math.sin(pitch),
            this.target.z + this.distance * Math.cos(yaw) * Math.cos(pitch),
        );
        this.camera.lookAt(this.target);
    }
    // Pull the camera back until a scene of the given half-width fits horizontally.
    fitWidth(aspect, halfWidth, nearest) {
        const tan = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
        this.distance = Math.max(nearest, halfWidth / (tan * aspect));
    }
    resize() {
        const { width, height } = this.host.getBoundingClientRect();
        if (!width || !height) return;
        this.renderer.setSize(width, height, false);
        this.camera.aspect = width / height;
        this.fit?.(width / height);
        this.camera.updateProjectionMatrix();
        this.kick();
    }
    kick() {
        if (this.frame == null)
            this.frame = requestAnimationFrame((now) => this.loop(now));
    }
    loop(now) {
        this.frame = null;
        if (!this.visible || document.hidden) return;
        const dt = Math.min(0.05, (now - this.last) / 1000);
        this.last = now;
        const busy = this.step?.(now, dt) ?? false;
        this.placeCamera();
        this.renderer.render(this.scene, this.camera);
        this.overlay?.();
        if (busy) this.kick();
    }
    project(vector) {
        const p = vector.clone().project(this.camera);
        const { width, height } = this.canvas.getBoundingClientRect();
        return {
            x: (p.x * 0.5 + 0.5) * width,
            y: (-p.y * 0.5 + 0.5) * height,
            behind: p.z > 1,
        };
    }
}

// The five recorded engine stages as glass gates along a track. Each recorded event
// becomes one particle travelling between the stages it actually reached.
const STAGE_IDS = ["data", "strategy", "risk", "execution", "journal"];

export class PipelineScene extends BaseScene {
    constructor(host, { onSelect } = {}) {
        super(host, { fov: 34 });
        this.onSelect = onSelect;
        this.baseYaw = 0.0;
        this.basePitch = 0.3;
        this.target.set(0, 1.15, 0.2);
        this.labels = host.querySelector(".scene-labels");
        this.selected = "strategy";
        this.lastSeq = null;
        this.queue = [];
        this.particles = [];
        this.rise = reducedMotion() ? 1 : 0;
        this.build();
    }
    build() {
        const floor = new THREE.Mesh(
            new THREE.CircleGeometry(6.5, 64),
            new THREE.MeshBasicMaterial({
                map: dotTexture(),
                transparent: true,
                depthWrite: false,
            }),
        );
        floor.rotation.x = -Math.PI / 2;
        this.scene.add(floor);
        // Gate centres on a gentle arc; the funnel narrows from data to journal.
        this.gates = [];
        const points = [];
        const radius = 5.4;
        STAGE_IDS.forEach((id, index) => {
            const angle = -0.62 + (index / 4) * 1.24;
            const scale = 1 - index * 0.09;
            points.push(
                new THREE.Vector3(
                    radius * Math.sin(angle),
                    0.98 * scale,
                    radius * (1 - Math.cos(angle)) - 1.1,
                ),
            );
            this.gates.push({ id, scale, pulse: 0 });
        });
        const lead = points[0]
            .clone()
            .add(points[0].clone().sub(points[1]).multiplyScalar(0.8));
        const tail = points[4]
            .clone()
            .add(points[4].clone().sub(points[3]).multiplyScalar(0.55));
        this.curve = new THREE.CatmullRomCurve3([lead, ...points, tail]);
        this.gateT = points.map((_, index) => (index + 1) / 6);
        this.scene.add(
            new THREE.Mesh(
                new THREE.TubeGeometry(this.curve, 160, 0.022, 8, false),
                new THREE.MeshStandardMaterial({
                    color: BRAND.lavender,
                    roughness: 0.6,
                }),
            ),
        );
        const frame = (scale) => {
            const w = 1.9 * scale,
                h = 1.55 * scale,
                r = 0.22 * scale,
                inset = 0.16;
            const rounded = (shape, x, y, width, height, radius) => {
                shape.moveTo(x + radius, y);
                shape.lineTo(x + width - radius, y);
                shape.quadraticCurveTo(x + width, y, x + width, y + radius);
                shape.lineTo(x + width, y + height - radius);
                shape.quadraticCurveTo(
                    x + width,
                    y + height,
                    x + width - radius,
                    y + height,
                );
                shape.lineTo(x + radius, y + height);
                shape.quadraticCurveTo(x, y + height, x, y + height - radius);
                shape.lineTo(x, y + radius);
                shape.quadraticCurveTo(x, y, x + radius, y);
                return shape;
            };
            const outer = rounded(new THREE.Shape(), -w / 2, -h / 2, w, h, r);
            outer.holes.push(
                rounded(
                    new THREE.Path(),
                    -w / 2 + inset,
                    -h / 2 + inset,
                    w - 2 * inset,
                    h - 2 * inset,
                    Math.max(0.04, r - inset * 0.6),
                ),
            );
            const geometry = new THREE.ExtrudeGeometry(outer, {
                depth: 0.16,
                bevelEnabled: true,
                bevelThickness: 0.03,
                bevelSize: 0.03,
                bevelSegments: 3,
                curveSegments: 10,
            });
            geometry.translate(0, 0, -0.08);
            return geometry;
        };
        const tangent = new THREE.Vector3();
        this.gates.forEach((gate, index) => {
            const material = new THREE.MeshStandardMaterial({
                color: 0xffffff,
                emissive: BRAND.purple,
                emissiveIntensity: 0,
                roughness: 0.35,
                metalness: 0.05,
                transparent: true,
                opacity: 0.92,
            });
            const mesh = new THREE.Mesh(frame(gate.scale), material);
            const pane = new THREE.Mesh(
                new THREE.PlaneGeometry(1.55 * gate.scale, 1.2 * gate.scale),
                new THREE.MeshBasicMaterial({
                    color: BRAND.mist,
                    transparent: true,
                    opacity: 0.35,
                    side: THREE.DoubleSide,
                    depthWrite: false,
                }),
            );
            const edges = new THREE.LineSegments(
                new THREE.EdgesGeometry(mesh.geometry, 30),
                new THREE.LineBasicMaterial({
                    color: BRAND.edge,
                    transparent: true,
                    opacity: 0.7,
                }),
            );
            const group = new THREE.Group();
            group.add(mesh, pane, edges);
            const position = this.curve.getPoint(this.gateT[index]);
            this.curve.getTangent(this.gateT[index], tangent);
            group.position.copy(position);
            // Face halfway between the track and the viewer: particles still pass
            // through each gate, and the gate reads as a frame rather than a sliver.
            const facing = tangent
                .clone()
                .normalize()
                .add(new THREE.Vector3(0, 0, 1.15));
            group.lookAt(position.clone().add(facing));
            group.userData.stage = gate.id;
            mesh.userData.stage = gate.id;
            this.scene.add(group);
            const shadow = new THREE.Mesh(
                new THREE.CircleGeometry(0.95 * gate.scale, 32),
                new THREE.MeshBasicMaterial({
                    color: BRAND.violet,
                    transparent: true,
                    opacity: 0.1,
                    depthWrite: false,
                }),
            );
            shadow.rotation.x = -Math.PI / 2;
            shadow.position.set(position.x, 0.005, position.z);
            shadow.scale.set(1, 0.45, 1);
            this.scene.add(shadow);
            Object.assign(gate, {
                group,
                mesh,
                material,
                edges,
                home: position.clone(),
            });
        });
        this.dots = new THREE.InstancedMesh(
            new THREE.SphereGeometry(0.075, 14, 14),
            new THREE.MeshBasicMaterial({ color: 0xffffff }),
            160,
        );
        this.dots.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        this.dots.count = 0;
        this.scene.add(this.dots);
        this.rings = Array.from({ length: 6 }, () => {
            const ring = new THREE.Mesh(
                new THREE.RingGeometry(0.32, 0.38, 48),
                new THREE.MeshBasicMaterial({
                    color: BRAND.green,
                    transparent: true,
                    opacity: 0,
                    side: THREE.DoubleSide,
                    depthWrite: false,
                }),
            );
            ring.visible = false;
            ring.userData.life = 0;
            this.scene.add(ring);
            return ring;
        });
        this.raycaster = new THREE.Raycaster();
        this.kick();
    }
    fit(aspect) {
        this.fitWidth(aspect, 4.4, 9.4);
    }
    // Map a recorded event to the stretch of the pipeline it actually covered.
    route(event) {
        const T = this.gateT;
        switch (event.kind) {
            case "quote":
                return { from: 0, to: T[1], fate: "fade", color: BRAND.violet };
            case "quote_rejected":
                return { from: 0, to: T[0], fate: "block", color: BRAND.red };
            case "strategy_blocked":
                return {
                    from: T[0],
                    to: T[1],
                    fate: "block",
                    color: BRAND.red,
                };
            case "decision":
                return event.side === "sell"
                    ? {
                          from: T[1],
                          to: T[3],
                          fate: "fade",
                          color: BRAND.purple,
                      }
                    : {
                          from: T[1],
                          to: T[2],
                          fate: "fade",
                          color: BRAND.purple,
                      };
            case "entry_blocked":
                return {
                    from: T[1],
                    to: T[2],
                    fate: "block",
                    color: BRAND.red,
                };
            case "risk_passed":
                return {
                    from: T[2],
                    to: T[3],
                    fate: "fade",
                    color: BRAND.purple,
                };
            case "order":
                return event.status === "rejected"
                    ? { from: T[2], to: T[3], fate: "block", color: BRAND.red }
                    : {
                          from: T[3],
                          to: T[4],
                          fate: "land",
                          color: BRAND.green,
                      };
            default:
                return null;
        }
    }
    update(state, counts, selected) {
        this.selected = selected;
        this.counts = counts;
        const events = state?.events || [];
        const newest = events.reduce((max, e) => Math.max(max, e.seq || 0), 0);
        // History already on screen is summarised by the counts, not replayed as motion.
        if (this.lastSeq == null || newest < this.lastSeq)
            this.lastSeq = newest;
        else if (newest > this.lastSeq) {
            if (!reducedMotion()) {
                const fresh = events.filter((e) => e.seq > this.lastSeq);
                for (const event of fresh.slice(-40)) {
                    const route = this.route(event);
                    if (route) this.queue.push(route);
                }
            }
            this.lastSeq = newest;
        }
        this.renderLabels();
        this.kick();
    }
    renderLabels() {
        if (!this.labels) return;
        const names = {
            data: "Data sentinel",
            strategy: "Setup scout",
            risk: "Risk guardian",
            execution: "Paper executor",
            journal: "Journal keeper",
        };
        if (!this.labels.childElementCount) {
            this.labels.innerHTML = STAGE_IDS.map(
                (id, index) =>
                    `<button class="scene-label" data-stage="${id}" aria-pressed="false"><span class="scene-label-step">${index + 1}</span><span class="scene-label-name">${names[id]}</span><span class="scene-label-count">0</span></button>`,
            ).join("");
            this.labels
                .querySelectorAll("[data-stage]")
                .forEach((button) =>
                    button.addEventListener("click", () =>
                        this.onSelect?.(button.dataset.stage),
                    ),
                );
        }
        this.labels.querySelectorAll("[data-stage]").forEach((button) => {
            const id = button.dataset.stage;
            const on = id === this.selected;
            button.classList.toggle("selected", on);
            button.setAttribute("aria-pressed", String(on));
            button.classList.toggle(
                "blocked",
                Boolean(this.counts?.blocked?.includes(id)),
            );
            const count = button.querySelector(".scene-label-count");
            const value = String(this.counts?.[id] ?? 0);
            if (count.textContent !== value) {
                count.textContent = value;
                if (!reducedMotion()) {
                    count.classList.remove("bump");
                    void count.offsetWidth;
                    count.classList.add("bump");
                }
            }
        });
    }
    step(now, dt) {
        let busy = false;
        if (this.rise < 1) {
            this.rise = Math.min(1, this.rise + dt / 1.6);
            busy = true;
        }
        // Release queued particles in a readable stream rather than a burst.
        this.spawnClock = (this.spawnClock || 0) - dt;
        if (this.queue.length && this.spawnClock <= 0) {
            const route = this.queue.shift();
            this.particles.push({ ...route, age: 0, duration: 1.15, drop: 0 });
            this.spawnClock = Math.max(0.05, 0.6 / (this.queue.length + 1));
        }
        if (this.queue.length) busy = true;
        const matrix = new THREE.Matrix4(),
            color = new THREE.Color(),
            point = new THREE.Vector3();
        let n = 0;
        this.particles = this.particles.filter((p) => {
            p.age += dt;
            const k = Math.min(1, p.age / p.duration);
            const t = p.from + (p.to - p.from) * ease(k);
            this.curve.getPoint(t, point);
            let scale = 1;
            if (k >= 1) {
                if (!p.arrived) {
                    p.arrived = true;
                    const gate = this.gates[this.gateT.indexOf(p.to)];
                    if (gate) gate.pulse = p.fate === "block" ? -1 : 1;
                    if (p.fate === "land") this.ring(point);
                }
                p.drop += dt;
                if (p.fate === "block") {
                    point.y -= 2.4 * p.drop * p.drop;
                    point.x += p.drop * 0.3;
                }
                scale = Math.max(
                    0,
                    1 - p.drop / (p.fate === "block" ? 0.9 : 0.35),
                );
                if (scale <= 0) return false;
            }
            matrix.makeScale(scale, scale, scale).setPosition(point);
            this.dots.setMatrixAt(n, matrix);
            this.dots.setColorAt(n, color.setHex(p.color));
            n += 1;
            return n < 160;
        });
        this.dots.count = n;
        this.dots.instanceMatrix.needsUpdate = true;
        if (this.dots.instanceColor) this.dots.instanceColor.needsUpdate = true;
        if (n) busy = true;
        for (const ring of this.rings) {
            if (!ring.visible) continue;
            ring.userData.life += dt;
            const life = ring.userData.life / 0.9;
            ring.scale.setScalar(1 + life * 1.6);
            ring.material.opacity = Math.max(0, 0.7 * (1 - life));
            if (life >= 1) ring.visible = false;
            else busy = true;
        }
        this.gates.forEach((gate, index) => {
            const delay = index * 0.12;
            const r = ease(clamp((this.rise - delay) / (1 - 0.48), 0, 1));
            const selected = gate.id === this.selected;
            const lift = selected ? 0.14 : 0;
            gate.group.position.set(
                gate.home.x,
                gate.home.y - (1 - r) * 1.4 + lift,
                gate.home.z,
            );
            gate.group.scale.setScalar(0.6 + 0.4 * r);
            const glow = selected ? 0.16 : 0.0;
            if (gate.pulse) {
                gate.pulse *= Math.exp(-dt * 4.5);
                if (Math.abs(gate.pulse) < 0.02) gate.pulse = 0;
                else busy = true;
            }
            gate.material.emissive.setHex(
                gate.pulse < 0 ? BRAND.red : BRAND.purple,
            );
            gate.material.emissiveIntensity =
                glow + Math.abs(gate.pulse) * 0.45;
            gate.edges.material.color.setHex(
                selected ? BRAND.purple : BRAND.edge,
            );
        });
        return busy;
    }
    ring(point) {
        const ring = this.rings.find((item) => !item.visible) || this.rings[0];
        ring.position.copy(point);
        ring.lookAt(this.camera.position);
        ring.userData.life = 0;
        ring.visible = true;
    }
    overlay() {
        if (!this.labels) return;
        const top = new THREE.Vector3();
        this.labels
            .querySelectorAll("[data-stage]")
            .forEach((button, index) => {
                const gate = this.gates[index];
                const below = index % 2 === 1;
                top.copy(gate.group.position);
                top.y += below
                    ? -(0.78 * gate.scale + 0.22)
                    : 0.78 * gate.scale + 0.3;
                const p = this.project(top);
                button.style.transform = `translate(${p.x}px, ${p.y}px) translate(-50%, ${below ? "0%" : "-100%"})`;
                button.style.opacity = p.behind ? "0" : "";
            });
    }
    click(event) {
        const box = this.canvas.getBoundingClientRect();
        const pointer = new THREE.Vector2(
            ((event.clientX - box.left) / box.width) * 2 - 1,
            -((event.clientY - box.top) / box.height) * 2 + 1,
        );
        this.raycaster.setFromCamera(pointer, this.camera);
        const hit = this.raycaster.intersectObjects(
            this.gates.map((gate) => gate.mesh),
        )[0];
        if (hit) this.onSelect?.(hit.object.userData.stage);
    }
}

// The replayed session as a 3D ribbon: price drawn left to right as observations
// arrive, with the recorded entry and exit pins and the planned stop/target planes.
const IST_OFFSET = 330;
const minutesIST = (iso) => {
    const date = new Date(iso);
    return (
        ((date.getUTCHours() * 60 + date.getUTCMinutes() + IST_OFFSET) % 1440) +
        date.getUTCSeconds() / 60
    );
};
const OPEN = 9 * 60 + 15,
    CLOSE = 15 * 60 + 30;

export class TapeScene extends BaseScene {
    constructor(host) {
        super(host, { fov: 30 });
        this.basePitch = 0.34;
        this.baseYaw = -0.32;
        this.target.set(0.2, 0.95, 0);
        this.overlayEl = host.querySelector(".tape-overlay");
        this.tooltip = host.querySelector(".tape-tooltip");
        this.width = 8.4;
        this.height = 2.3;
        this.depth = 0.42;
        this.signature = "";
        this.shown = 0;
        this.goal = 0;
        this.points = [];
        this.build();
    }
    fit(aspect) {
        this.fitWidth(aspect, 5.2, 9.2);
    }
    build() {
        const floor = new THREE.Mesh(
            new THREE.PlaneGeometry(this.width + 1.2, 3.2),
            new THREE.MeshBasicMaterial({
                color: BRAND.mist,
                transparent: true,
                opacity: 0.55,
                depthWrite: false,
            }),
        );
        floor.rotation.x = -Math.PI / 2;
        this.scene.add(floor);
        const ticks = [];
        for (let m = 10 * 60; m < CLOSE; m += 60) {
            const x = this.x(m);
            ticks.push(x, 0.002, -1.4, x, 0.002, 1.4);
        }
        const grid = new THREE.BufferGeometry();
        grid.setAttribute(
            "position",
            new THREE.Float32BufferAttribute(ticks, 3),
        );
        this.scene.add(
            new THREE.LineSegments(
                grid,
                new THREE.LineBasicMaterial({
                    color: BRAND.lavender,
                    transparent: true,
                    opacity: 0.9,
                }),
            ),
        );
        this.top = new THREE.Mesh(
            new THREE.BufferGeometry(),
            new THREE.MeshStandardMaterial({
                color: 0xc9bbf0,
                emissive: BRAND.purple,
                emissiveIntensity: 0.12,
                roughness: 0.45,
                side: THREE.DoubleSide,
            }),
        );
        this.curtain = new THREE.Mesh(
            new THREE.BufferGeometry(),
            new THREE.MeshBasicMaterial({
                vertexColors: true,
                transparent: true,
                side: THREE.DoubleSide,
                depthWrite: false,
            }),
        );
        this.line = new THREE.Line(
            new THREE.BufferGeometry(),
            new THREE.LineBasicMaterial({ color: BRAND.purple }),
        );
        this.scene.add(this.curtain, this.top, this.line);
        this.planes = new THREE.Group();
        this.pins = new THREE.Group();
        this.scene.add(this.planes, this.pins);
    }
    x(minutes) {
        return ((minutes - OPEN) / (CLOSE - OPEN) - 0.5) * this.width;
    }
    y(price) {
        const { lo, hi } = this.range;
        return 0.25 + ((price - lo) / (hi - lo || 1)) * this.height;
    }
    update(state) {
        const prices = (state?.prices || []).filter(
            (p) => p.at && Number.isFinite(Number(p.price)),
        );
        const calls = (state?.calls || []).filter((c) => c.fill_inr != null);
        const signature = `${state?.run_id}|${prices.length}|${calls.length}|${prices.at(-1)?.price}`;
        if (signature === this.signature) return;
        const sameRun = this.signature.startsWith(`${state?.run_id}|`);
        this.signature = signature;
        this.points = prices.map((p) => ({
            m: minutesIST(p.at),
            price: Number(p.price),
            at: p.at,
        }));
        const values = this.points.map((p) => p.price);
        for (const call of calls)
            for (const key of ["fill_inr", "stop", "target"])
                if (call[key] != null) values.push(Number(call[key]));
        const lo = Math.min(...values),
            hi = Math.max(...values);
        const pad = (hi - lo || hi * 0.01 || 1) * 0.12;
        this.range = values.length
            ? { lo: lo - pad, hi: hi + pad }
            : { lo: 0, hi: 1 };
        this.calls = calls;
        this.goal = this.points.length;
        // A page load shows the recorded session at once; a new run draws in, and a
        // running session extends the ribbon as each observation is recorded.
        const firstPaint = !this.painted;
        this.painted = true;
        if (firstPaint || reducedMotion()) this.shown = this.goal;
        else if (!sameRun) this.shown = 0;
        this.buildPins();
        this.buildLabels();
        this.host.classList.toggle("empty", !this.points.length);
        this.kick();
    }
    rebuildRibbon(count) {
        const pts = this.points.slice(0, Math.max(0, Math.ceil(count)));
        const top = [],
            curtain = [],
            colors = [],
            line = [];
        const d = this.depth;
        for (let i = 0; i < pts.length; i++) {
            const x = this.x(pts[i].m),
                y = this.y(pts[i].price);
            line.push(x, y, d);
            if (i === 0) continue;
            const px = this.x(pts[i - 1].m),
                py = this.y(pts[i - 1].price);
            top.push(
                px,
                py,
                -d,
                x,
                y,
                -d,
                x,
                y,
                d,
                px,
                py,
                -d,
                x,
                y,
                d,
                px,
                py,
                d,
            );
            curtain.push(
                px,
                py,
                d,
                x,
                y,
                d,
                x,
                0,
                d,
                px,
                py,
                d,
                x,
                0,
                d,
                px,
                0,
                d,
            );
            for (const alpha of [0.5, 0.5, 0, 0.5, 0, 0])
                colors.push(0.62, 0.52, 0.86, alpha);
        }
        const set = (mesh, position, color) => {
            mesh.geometry.dispose();
            mesh.geometry = new THREE.BufferGeometry();
            mesh.geometry.setAttribute(
                "position",
                new THREE.Float32BufferAttribute(position, 3),
            );
            if (color)
                mesh.geometry.setAttribute(
                    "color",
                    new THREE.Float32BufferAttribute(color, 4),
                );
            mesh.geometry.computeVertexNormals();
        };
        set(this.top, top);
        set(this.curtain, curtain, colors);
        set(this.line, line);
        this.drawn = pts.length;
    }
    buildPins() {
        for (const group of [this.pins, this.planes]) {
            group.children.forEach((child) => {
                child.geometry?.dispose();
                child.material?.dispose();
            });
            group.clear();
        }
        const last = this.points.at(-1)?.m ?? OPEN;
        const entry = this.calls.find((c) => c.side === "buy");
        const exit = this.calls.find((c) => c.side === "sell");
        for (const call of this.calls) {
            const color = call.side === "buy" ? BRAND.green : BRAND.purple;
            const x = this.x(minutesIST(call.at)),
                y = this.y(Number(call.fill_inr));
            const stick = new THREE.Mesh(
                new THREE.CylinderGeometry(0.012, 0.012, y, 8),
                new THREE.MeshBasicMaterial({
                    color,
                    transparent: true,
                    opacity: 0.55,
                }),
            );
            stick.position.set(x, y / 2, this.depth);
            const head = new THREE.Mesh(
                new THREE.SphereGeometry(0.1, 20, 20),
                new THREE.MeshStandardMaterial({
                    color,
                    emissive: color,
                    emissiveIntensity: 0.35,
                }),
            );
            head.position.set(x, y, this.depth);
            head.userData.call = call;
            this.pins.add(stick, head);
        }
        if (entry && (entry.stop != null || entry.target != null)) {
            const from = this.x(minutesIST(entry.at)),
                to = this.x(exit ? minutesIST(exit.at) : last);
            for (const [key, color] of [
                ["stop", BRAND.red],
                ["target", BRAND.green],
            ]) {
                if (entry[key] == null) continue;
                const width = Math.max(0.05, to - from);
                const plane = new THREE.Mesh(
                    new THREE.PlaneGeometry(width, this.depth * 2 + 0.5),
                    new THREE.MeshBasicMaterial({
                        color,
                        transparent: true,
                        opacity: 0.13,
                        side: THREE.DoubleSide,
                        depthWrite: false,
                    }),
                );
                plane.rotation.x = -Math.PI / 2;
                plane.position.set(
                    from + width / 2,
                    this.y(Number(entry[key])),
                    0,
                );
                const edge = new THREE.LineSegments(
                    new THREE.EdgesGeometry(plane.geometry),
                    new THREE.LineBasicMaterial({
                        color,
                        transparent: true,
                        opacity: 0.45,
                    }),
                );
                edge.rotation.copy(plane.rotation);
                edge.position.copy(plane.position);
                plane.userData.plan = key;
                this.planes.add(plane, edge);
            }
        }
    }
    buildLabels() {
        if (!this.overlayEl) return;
        const money = (v) =>
            new Intl.NumberFormat("en-IN", {
                style: "currency",
                currency: "INR",
            }).format(v);
        const items = [];
        for (let m = 10 * 60; m < CLOSE; m += 60)
            items.push({
                kind: "time",
                text: `${String(Math.floor(m / 60)).padStart(2, "0")}:00`,
                at: new THREE.Vector3(this.x(m), 0, 1.5),
            });
        for (const call of this.calls)
            items.push({
                kind: call.side === "buy" ? "pin buy" : "pin sell",
                text: `${call.side === "buy" ? "Bought" : "Sold"} ${money(Number(call.fill_inr))}`,
                at: new THREE.Vector3(
                    this.x(minutesIST(call.at)),
                    this.y(Number(call.fill_inr)) + 0.28,
                    this.depth,
                ),
            });
        const entry = this.calls.find((c) => c.side === "buy");
        const exit = this.calls.find((c) => c.side === "sell");
        const end = exit
            ? minutesIST(exit.at)
            : (this.points.at(-1)?.m ?? minutesIST(entry?.at ?? OPEN));
        if (entry)
            for (const key of ["stop", "target"])
                if (entry[key] != null)
                    items.push({
                        kind: `plan ${key}`,
                        text: `${key === "stop" ? "Stop" : "Target"} ${money(Number(entry[key]))}`,
                        at: new THREE.Vector3(
                            this.x(end) + 0.12,
                            this.y(Number(entry[key])),
                            this.depth + 0.25,
                        ),
                    });
        this.items = items;
        this.overlayEl.innerHTML = items
            .map(
                (item) =>
                    `<span class="tape-label ${item.kind}">${item.text}</span>`,
            )
            .join("");
    }
    step(now, dt) {
        if (this.shown < this.goal) {
            this.shown = Math.min(this.goal, this.shown + dt * 28);
        }
        if (Math.ceil(this.shown) !== this.drawn)
            this.rebuildRibbon(this.shown);
        const reveal =
            this.points[Math.max(0, Math.ceil(this.shown) - 1)]?.m ?? OPEN;
        for (const child of this.pins.children)
            child.visible =
                !child.userData.call ||
                minutesIST(child.userData.call.at) <= reveal + 0.01;
        return this.shown < this.goal;
    }
    overlay() {
        if (!this.overlayEl || !this.items) return;
        const reveal =
            this.points[Math.max(0, Math.ceil(this.shown) - 1)]?.m ?? OPEN;
        [...this.overlayEl.children].forEach((element, index) => {
            const item = this.items[index];
            const p = this.project(item.at);
            const hidden =
                p.behind ||
                (item.kind.startsWith("pin") &&
                    this.x(reveal) + 1e-6 < item.at.x);
            const anchor = item.kind.startsWith("plan")
                ? "translate(0, -50%)"
                : "translate(-50%, -100%)";
            element.style.transform = `translate(${p.x}px, ${p.y}px) ${anchor}`;
            element.style.opacity = hidden ? "0" : "";
        });
    }
    hover(event) {
        if (!this.tooltip || !this.points.length) return;
        const box = this.canvas.getBoundingClientRect();
        const mouse = event.clientX - box.left;
        let best = null;
        for (const point of this.points.slice(0, Math.ceil(this.shown))) {
            const p = this.project(
                new THREE.Vector3(
                    this.x(point.m),
                    this.y(point.price),
                    this.depth,
                ),
            );
            const distance = Math.abs(p.x - mouse);
            if (!best || distance < best.distance)
                best = { distance, p, point };
        }
        if (!best || best.distance > 24) return this.leave();
        const time = new Intl.DateTimeFormat("en-IN", {
            timeZone: "Asia/Kolkata",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
        }).format(new Date(best.point.at));
        this.tooltip.textContent = `${time} IST · bid ${new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(best.point.price)}`;
        this.tooltip.style.transform = `translate(${best.p.x}px, ${best.p.y}px) translate(-50%, -140%)`;
        this.tooltip.classList.add("show");
    }
    leave() {
        this.tooltip?.classList.remove("show");
    }
}
