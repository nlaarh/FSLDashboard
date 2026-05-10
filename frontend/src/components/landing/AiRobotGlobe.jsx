import { useEffect, useRef } from 'react'
import * as THREE from 'three'

/* ── Three.js globe sized for the robot chest window ── */
function ChestGlobe() {
  const mountRef = useRef(null)

  useEffect(() => {
    const container = mountRef.current
    if (!container) return
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(58, container.clientWidth / container.clientHeight, 0.1, 100)
    camera.position.z = 2.2

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
    renderer.setSize(container.clientWidth, container.clientHeight)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    container.appendChild(renderer.domElement)

    const g = new THREE.Group()
    scene.add(g)

    // Core pulsing sphere
    const coreGeo = new THREE.SphereGeometry(0.42, 48, 48)
    const coreMat = new THREE.MeshBasicMaterial({ color: '#f59e0b', transparent: true, opacity: 0 })
    const core = new THREE.Mesh(coreGeo, coreMat)
    g.add(core)

    // Wireframe cage
    const cageGeo = new THREE.SphereGeometry(0.52, 14, 10)
    const cageMat = new THREE.MeshBasicMaterial({ color: '#f59e0b', transparent: true, opacity: 0, wireframe: true })
    const cage = new THREE.Mesh(cageGeo, cageMat)
    g.add(cage)

    // Particles
    const N = 220, R = 1.0
    const pos = new Float32Array(N * 3)
    const col = new Float32Array(N * 3)
    const amber = new THREE.Color('#f59e0b')
    const gold  = new THREE.Color('#fbbf24')
    const red   = new THREE.Color('#ef4444')
    const white = new THREE.Color('#ffffff')
    for (let i = 0; i < N; i++) {
      const phi = Math.acos(2 * Math.random() - 1)
      const theta = Math.random() * Math.PI * 2
      pos[i*3]   = R * Math.sin(phi) * Math.cos(theta)
      pos[i*3+1] = R * Math.sin(phi) * Math.sin(theta)
      pos[i*3+2] = R * Math.cos(phi)
      const r = Math.random()
      const c = r < 0.45 ? amber : r < 0.75 ? gold : r < 0.9 ? red : white
      col[i*3] = c.r; col[i*3+1] = c.g; col[i*3+2] = c.b
    }
    const ptGeo = new THREE.BufferGeometry()
    ptGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    ptGeo.setAttribute('color',    new THREE.BufferAttribute(col, 3))
    const ptMat = new THREE.PointsMaterial({ size: 0.042, vertexColors: true, transparent: true, opacity: 0, sizeAttenuation: true })
    const pts = new THREE.Points(ptGeo, ptMat)
    g.add(pts)

    // Connection lines
    const LC = 30
    const lpos = new Float32Array(LC * 6)
    for (let i = 0; i < LC; i++) {
      const a = Math.floor(Math.random() * N), b = Math.floor(Math.random() * N)
      for (let j = 0; j < 3; j++) { lpos[i*6+j] = pos[a*3+j]; lpos[i*6+3+j] = pos[b*3+j] }
    }
    const lGeo = new THREE.BufferGeometry()
    lGeo.setAttribute('position', new THREE.BufferAttribute(lpos, 3))
    const lMat = new THREE.LineBasicMaterial({ color: '#f59e0b', transparent: true, opacity: 0 })
    const lines = new THREE.LineSegments(lGeo, lMat)
    g.add(lines)

    // Rings
    const mkRing = (r1, r2, col, tiltX, tiltZ) => {
      const geo = new THREE.RingGeometry(r1, r2, 96)
      const mat = new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0, side: THREE.DoubleSide })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.rotation.x = tiltX; mesh.rotation.z = tiltZ
      g.add(mesh)
      return { mesh, mat }
    }
    const r1 = mkRing(R+0.03, R+0.055, '#f59e0b', Math.PI/2, 0)
    const r2 = mkRing(R+0.14, R+0.16,  '#ef4444', Math.PI/2, Math.PI/5)
    const r3 = mkRing(R+0.27, R+0.29,  '#fbbf24', Math.PI*0.38, 0.2)

    // Animate
    let animId, fade = 0
    const FADE = 100, rot = prefersReduced ? 0 : 0.008

    const animate = () => {
      animId = requestAnimationFrame(animate)
      const t = Date.now()

      if (fade < FADE) {
        fade++
        const o = fade / FADE
        ptMat.opacity  = 0.82 * o
        lMat.opacity   = 0.12 * o
        r1.mat.opacity = 0.38 * o
        r2.mat.opacity = 0.22 * o
        r3.mat.opacity = 0.14 * o
        coreMat.opacity = 0.6 * o
        cageMat.opacity = 0.20 * o
      }

      pts.rotation.y  += rot
      lines.rotation.y += rot
      r1.mesh.rotation.z += rot * 0.7
      r2.mesh.rotation.z -= rot * 1.2
      r3.mesh.rotation.z += rot * 0.45
      cage.rotation.y += rot * 0.55
      cage.rotation.x += rot * 0.25

      const p = 0.5 + 0.5 * Math.sin(t * 0.002)
      coreMat.opacity  = (fade >= FADE ? 0.55 : (fade/FADE)*0.55) * (0.65 + 0.35*p)
      cageMat.opacity  = 0.10 + 0.14*p
      r1.mat.opacity   = 0.25 + 0.15 * Math.sin(t * 0.0012)
      lMat.opacity     = 0.08 + 0.06 * Math.sin(t * 0.0009)

      renderer.render(scene, camera)
    }
    animate()

    const onResize = () => {
      if (!container) return
      camera.aspect = container.clientWidth / container.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(container.clientWidth, container.clientHeight)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', onResize)
      renderer.dispose()
      ;[coreGeo, coreMat, cageGeo, cageMat, ptGeo, ptMat, lGeo, lMat,
        r1.mesh.geometry, r1.mat, r2.mesh.geometry, r2.mat, r3.mesh.geometry, r3.mat
      ].forEach(o => o.dispose?.())
      if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement)
    }
  }, [])

  return <div ref={mountRef} style={{ width: '100%', height: '100%' }} />
}

/* ── Robot SVG dimensions (unitless — viewBox drives scale) ── */
const VW = 300, VH = 490

export default function AiRobotGlobe({ style }) {
  // Chest window bounds (must match SVG rect below)
  const CHEST = { x: 32, y: 172, w: 236, h: 178 }

  return (
    <div style={{ position: 'relative', width: VW, height: VH, ...style }}>

      {/* ── Three.js globe behind the SVG, clipped to chest shape ── */}
      <div style={{
        position: 'absolute',
        top: CHEST.y, left: CHEST.x,
        width: CHEST.w, height: CHEST.h,
        borderRadius: 14,
        overflow: 'hidden',
        zIndex: 0,
      }}>
        <ChestGlobe />
      </div>

      {/* ── SVG robot body on top ── */}
      <svg
        viewBox={`0 0 ${VW} ${VH}`}
        width={VW} height={VH}
        style={{ position: 'absolute', inset: 0, zIndex: 1, overflow: 'visible' }}
        aria-hidden="true"
      >
        <defs>
          {/* Amber glow filter */}
          <filter id="rglow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="rglowSoft" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="eyeGlow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* ── Base body fill (silhouette) ── */}

        {/* Left ear */}
        <rect x="20" y="36" width="30" height="56" rx="8"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="26" y1="52" x2="44" y2="52" stroke="#f59e0b" strokeWidth="0.8" opacity="0.5" />
        <line x1="26" y1="60" x2="44" y2="60" stroke="#f59e0b" strokeWidth="0.8" opacity="0.5" />
        <line x1="26" y1="68" x2="44" y2="68" stroke="#f59e0b" strokeWidth="0.8" opacity="0.5" />

        {/* Right ear */}
        <rect x="250" y="36" width="30" height="56" rx="8"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="256" y1="52" x2="274" y2="52" stroke="#f59e0b" strokeWidth="0.8" opacity="0.5" />
        <line x1="256" y1="60" x2="274" y2="60" stroke="#f59e0b" strokeWidth="0.8" opacity="0.5" />
        <line x1="256" y1="68" x2="274" y2="68" stroke="#f59e0b" strokeWidth="0.8" opacity="0.5" />

        {/* Head */}
        <rect x="50" y="22" width="200" height="124" rx="18"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="2" />

        {/* Head top ridge */}
        <rect x="80" y="22" width="140" height="8" rx="4"
          fill="#f59e0b" opacity="0.18" />

        {/* Antenna base */}
        <rect x="145" y="10" width="10" height="14" rx="3"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        {/* Antenna arm */}
        <line x1="150" y1="10" x2="150" y2="2" stroke="#f59e0b" strokeWidth="1.8" />
        {/* Antenna tip — blinks red */}
        <circle cx="150" cy="2" r="5" fill="#ef4444" filter="url(#rglow)">
          <animate attributeName="opacity" values="1;0.2;1" dur="1.4s" repeatCount="indefinite" />
          <animate attributeName="r"       values="5;4;5"   dur="1.4s" repeatCount="indefinite" />
        </circle>

        {/* Left eye socket */}
        <circle cx="105" cy="78" r="20" fill="#060d1c" stroke="#f59e0b" strokeWidth="1.5" />
        {/* Left eye glow ring */}
        <circle cx="105" cy="78" r="14" fill="#f59e0b" opacity="0.12" filter="url(#eyeGlow)">
          <animate attributeName="opacity" values="0.12;0.3;0.12" dur="2.2s" repeatCount="indefinite" />
        </circle>
        {/* Left eye iris */}
        <circle cx="105" cy="78" r="10" fill="#f59e0b" filter="url(#eyeGlow)">
          <animate attributeName="r"       values="10;8;10"       dur="2.2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.9;1;0.9"     dur="2.2s" repeatCount="indefinite" />
        </circle>
        {/* Left pupil */}
        <circle cx="105" cy="78" r="4" fill="#0b1525" />

        {/* Right eye socket */}
        <circle cx="195" cy="78" r="20" fill="#060d1c" stroke="#f59e0b" strokeWidth="1.5" />
        {/* Right eye glow ring */}
        <circle cx="195" cy="78" r="14" fill="#f59e0b" opacity="0.12" filter="url(#eyeGlow)">
          <animate attributeName="opacity" values="0.12;0.3;0.12" dur="2.2s" begin="0.3s" repeatCount="indefinite" />
        </circle>
        {/* Right eye iris */}
        <circle cx="195" cy="78" r="10" fill="#f59e0b" filter="url(#eyeGlow)">
          <animate attributeName="r"       values="10;8;10"       dur="2.2s" begin="0.3s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.9;1;0.9"     dur="2.2s" begin="0.3s" repeatCount="indefinite" />
        </circle>
        {/* Right pupil */}
        <circle cx="195" cy="78" r="4" fill="#0b1525" />

        {/* Blink lid — left */}
        <rect x="85" y="58" width="40" height="40" rx="20" fill="#0b1525" opacity="0">
          <animate attributeName="opacity" values="0;0;0;0;0;0;0;0;0;1;0" dur="5s" repeatCount="indefinite" />
        </rect>
        {/* Blink lid — right */}
        <rect x="175" y="58" width="40" height="40" rx="20" fill="#0b1525" opacity="0">
          <animate attributeName="opacity" values="0;0;0;0;0;0;0;0;0;1;0" dur="5s" begin="0.05s" repeatCount="indefinite" />
        </rect>

        {/* Chin detail line */}
        <line x1="68" y1="128" x2="232" y2="128" stroke="#f59e0b" strokeWidth="1" opacity="0.3" />

        {/* Status LEDs row on chin */}
        <circle cx="120" cy="138" r="3" fill="#22c55e">
          <animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite" />
        </circle>
        <circle cx="135" cy="138" r="3" fill="#f59e0b">
          <animate attributeName="opacity" values="1;0.3;1" dur="2s" begin="0.4s" repeatCount="indefinite" />
        </circle>
        <circle cx="150" cy="138" r="3" fill="#3b82f6">
          <animate attributeName="opacity" values="1;0.3;1" dur="2s" begin="0.8s" repeatCount="indefinite" />
        </circle>
        <circle cx="165" cy="138" r="3" fill="#f59e0b">
          <animate attributeName="opacity" values="1;0.3;1" dur="2s" begin="1.2s" repeatCount="indefinite" />
        </circle>
        <circle cx="180" cy="138" r="3" fill="#22c55e">
          <animate attributeName="opacity" values="1;0.3;1" dur="2s" begin="1.6s" repeatCount="indefinite" />
        </circle>

        {/* Neck */}
        <rect x="110" y="146" width="80" height="28" rx="8"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="125" y1="160" x2="175" y2="160" stroke="#f59e0b" strokeWidth="0.8" opacity="0.4" />

        {/* Left shoulder joint */}
        <circle cx="24" cy="194" r="12" fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <circle cx="24" cy="194" r="5"  fill="#f59e0b" opacity="0.3" />

        {/* Right shoulder joint */}
        <circle cx="276" cy="194" r="12" fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <circle cx="276" cy="194" r="5"  fill="#f59e0b" opacity="0.3" />

        {/* Left arm */}
        <rect x="2" y="190" width="24" height="118" rx="10"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="5"  y1="232" x2="24" y2="232" stroke="#f59e0b" strokeWidth="0.7" opacity="0.35" />
        <line x1="5"  y1="250" x2="24" y2="250" stroke="#f59e0b" strokeWidth="0.7" opacity="0.35" />
        {/* Left elbow */}
        <rect x="0" y="248" width="28" height="18" rx="6"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.2" />

        {/* Right arm */}
        <rect x="274" y="190" width="24" height="118" rx="10"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="276" y1="232" x2="295" y2="232" stroke="#f59e0b" strokeWidth="0.7" opacity="0.35" />
        <line x1="276" y1="250" x2="295" y2="250" stroke="#f59e0b" strokeWidth="0.7" opacity="0.35" />
        {/* Right elbow */}
        <rect x="272" y="248" width="28" height="18" rx="6"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.2" />

        {/* Left hand */}
        <rect x="0" y="302" width="28" height="26" rx="7"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="7"  y1="308" x2="7"  y2="321" stroke="#f59e0b" strokeWidth="0.8" opacity="0.4" />
        <line x1="14" y1="308" x2="14" y2="321" stroke="#f59e0b" strokeWidth="0.8" opacity="0.4" />
        <line x1="21" y1="308" x2="21" y2="321" stroke="#f59e0b" strokeWidth="0.8" opacity="0.4" />

        {/* Right hand */}
        <rect x="272" y="302" width="28" height="26" rx="7"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="279" y1="308" x2="279" y2="321" stroke="#f59e0b" strokeWidth="0.8" opacity="0.4" />
        <line x1="286" y1="308" x2="286" y2="321" stroke="#f59e0b" strokeWidth="0.8" opacity="0.4" />
        <line x1="293" y1="308" x2="293" y2="321" stroke="#f59e0b" strokeWidth="0.8" opacity="0.4" />

        {/* ── Chest frame (globe shows through — NO fill) ── */}
        <rect x="32" y="172" width="236" height="178" rx="14"
          fill="none" stroke="#f59e0b" strokeWidth="2.2" />

        {/* Chest corner accents */}
        <path d="M32 196 L32 172 L56 172"  fill="none" stroke="#fbbf24" strokeWidth="2.5" strokeLinecap="round" />
        <path d="M268 196 L268 172 L244 172" fill="none" stroke="#fbbf24" strokeWidth="2.5" strokeLinecap="round" />
        <path d="M32 326 L32 350 L56 350"  fill="none" stroke="#fbbf24" strokeWidth="2.5" strokeLinecap="round" />
        <path d="M268 326 L268 350 L244 350" fill="none" stroke="#fbbf24" strokeWidth="2.5" strokeLinecap="round" />

        {/* Chest scan-line shimmer */}
        <rect x="32" y="172" width="236" height="4" fill="#f59e0b" opacity="0.06" rx="2">
          <animateTransform attributeName="transform" type="translate" values="0,0;0,174;0,0" dur="3s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.06;0.16;0.06" dur="3s" repeatCount="indefinite" />
        </rect>

        {/* Chest bottom LED bar */}
        <rect x="90" y="356" width="120" height="8" rx="4"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1" />
        {[0,1,2,3,4].map(i => (
          <circle key={i} cx={106 + i * 22} cy="360" r="3" fill="#f59e0b" opacity="0.7">
            <animate attributeName="opacity" values="0.7;0.1;0.7" dur="1.8s" begin={`${i*0.28}s`} repeatCount="indefinite" />
          </circle>
        ))}

        {/* Waist */}
        <rect x="68" y="370" width="164" height="30" rx="10"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="78"  y1="385" x2="222" y2="385" stroke="#f59e0b" strokeWidth="0.7" opacity="0.3" />

        {/* Left leg */}
        <rect x="62" y="400" width="72" height="62" rx="10"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="70" y1="425" x2="126" y2="425" stroke="#f59e0b" strokeWidth="0.7" opacity="0.3" />
        <line x1="70" y1="440" x2="126" y2="440" stroke="#f59e0b" strokeWidth="0.7" opacity="0.3" />

        {/* Right leg */}
        <rect x="166" y="400" width="72" height="62" rx="10"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />
        <line x1="174" y1="425" x2="230" y2="425" stroke="#f59e0b" strokeWidth="0.7" opacity="0.3" />
        <line x1="174" y1="440" x2="230" y2="440" stroke="#f59e0b" strokeWidth="0.7" opacity="0.3" />

        {/* Left foot */}
        <rect x="50" y="454" width="94" height="24" rx="8"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />

        {/* Right foot */}
        <rect x="156" y="454" width="94" height="24" rx="8"
          fill="#0b1525" stroke="#f59e0b" strokeWidth="1.5" />

        {/* Ambient body glow (outermost, very soft) */}
        <rect x="32" y="172" width="236" height="178" rx="14"
          fill="none" stroke="#f59e0b" strokeWidth="8" opacity="0.04" filter="url(#rglowSoft)">
          <animate attributeName="opacity" values="0.04;0.1;0.04" dur="2.8s" repeatCount="indefinite" />
        </rect>
      </svg>
    </div>
  )
}
