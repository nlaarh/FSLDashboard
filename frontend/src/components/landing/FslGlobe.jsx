import { useEffect, useRef } from 'react'
import * as THREE from 'three'

export default function FslGlobe() {
  const mountRef = useRef(null)

  useEffect(() => {
    const container = mountRef.current
    if (!container) return
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.1, 1000)
    camera.position.z = 3.0
    camera.position.y = 0

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
    renderer.setSize(container.clientWidth, container.clientHeight)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    container.appendChild(renderer.domElement)

    const globeGroup = new THREE.Group()
    globeGroup.position.y = 0.3
    scene.add(globeGroup)

    // Central image disc — AI image inside the globe
    const textureLoader = new THREE.TextureLoader()
    const imageTexture = textureLoader.load('/hero-bg.jpg')
    imageTexture.colorSpace = THREE.SRGBColorSpace

    const imageDiscGeo = new THREE.CircleGeometry(0.75, 64)
    const imageDiscMat = new THREE.MeshBasicMaterial({
      map: imageTexture,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
    })
    const imageDisc = new THREE.Mesh(imageDiscGeo, imageDiscMat)
    globeGroup.add(imageDisc)

    // Glow ring around the image
    const innerRingGeo = new THREE.RingGeometry(0.73, 0.76, 64)
    const innerRingMat = new THREE.MeshBasicMaterial({
      color: '#06b6d4', transparent: true, opacity: 0, side: THREE.DoubleSide,
    })
    const innerRing = new THREE.Mesh(innerRingGeo, innerRingMat)
    globeGroup.add(innerRing)

    // Orbiting particles — SalesPulse blue/cyan palette
    const POINT_COUNT = 220
    const RADIUS = 1.2
    const positions = new Float32Array(POINT_COUNT * 3)
    const colors = new Float32Array(POINT_COUNT * 3)
    const blue = new THREE.Color('#3b82f6')
    const cyan = new THREE.Color('#06b6d4')

    for (let i = 0; i < POINT_COUNT; i++) {
      const phi   = Math.acos(2 * Math.random() - 1)
      const theta = Math.random() * Math.PI * 2
      positions[i * 3]     = RADIUS * Math.sin(phi) * Math.cos(theta)
      positions[i * 3 + 1] = RADIUS * Math.sin(phi) * Math.sin(theta)
      positions[i * 3 + 2] = RADIUS * Math.cos(phi)
      const c = Math.random() > 0.5 ? blue : cyan
      colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b
    }

    const pointGeo = new THREE.BufferGeometry()
    pointGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    pointGeo.setAttribute('color',    new THREE.BufferAttribute(colors, 3))
    const pointMat = new THREE.PointsMaterial({
      size: 0.035, vertexColors: true, transparent: true, opacity: 0, sizeAttenuation: true,
    })
    const points = new THREE.Points(pointGeo, pointMat)
    globeGroup.add(points)

    // Connection lines
    const LINE_COUNT = 30
    const linePositions = new Float32Array(LINE_COUNT * 6)
    for (let i = 0; i < LINE_COUNT; i++) {
      const a = Math.floor(Math.random() * POINT_COUNT)
      const b = Math.floor(Math.random() * POINT_COUNT)
      for (let j = 0; j < 3; j++) {
        linePositions[i * 6 + j]     = positions[a * 3 + j]
        linePositions[i * 6 + 3 + j] = positions[b * 3 + j]
      }
    }
    const lineGeo = new THREE.BufferGeometry()
    lineGeo.setAttribute('position', new THREE.BufferAttribute(linePositions, 3))
    const lineMat = new THREE.LineBasicMaterial({ color: '#06b6d4', transparent: true, opacity: 0 })
    const lines = new THREE.LineSegments(lineGeo, lineMat)
    globeGroup.add(lines)

    // Outer glow ring
    const ringGeo = new THREE.RingGeometry(RADIUS + 0.02, RADIUS + 0.04, 64)
    const ringMat = new THREE.MeshBasicMaterial({
      color: '#3b82f6', transparent: true, opacity: 0, side: THREE.DoubleSide,
    })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    globeGroup.add(ring)

    // Animate
    let animId
    let fadeProgress = 0
    const FADE_DURATION = 120
    const rotSpeed = prefersReduced ? 0 : 0.001

    const animate = () => {
      animId = requestAnimationFrame(animate)

      if (fadeProgress < FADE_DURATION) {
        fadeProgress++
        const o = fadeProgress / FADE_DURATION
        pointMat.opacity    = 0.85 * o
        lineMat.opacity     = 0.15 * o
        ringMat.opacity     = 0.12 * o
        imageDiscMat.opacity = 0.95 * o
        innerRingMat.opacity = 0.3 * o
      }

      points.rotation.y += rotSpeed
      lines.rotation.y  += rotSpeed
      ring.rotation.y   += rotSpeed

      // Same pulse logic as SalesPulse original
      innerRingMat.opacity = 0.2 + 0.1 * Math.sin(Date.now() * 0.002)
      lineMat.opacity      = 0.15 + 0.05 * Math.sin(Date.now() * 0.001)

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
      imageDiscGeo.dispose(); imageDiscMat.dispose(); imageTexture.dispose()
      innerRingGeo.dispose(); innerRingMat.dispose()
      pointGeo.dispose(); pointMat.dispose()
      lineGeo.dispose(); lineMat.dispose()
      ringGeo.dispose(); ringMat.dispose()
      if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement)
    }
  }, [])

  return (
    <div ref={mountRef} aria-hidden="true"
      style={{ position: 'absolute', inset: 0, zIndex: 0, pointerEvents: 'none' }}
    />
  )
}
