import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import './Landing.css'

const FslGlobe = lazy(() => import('../components/landing/FslGlobe'))

/* ── Logo — pulse-wave inside a circle ── */
function Logo({ size = 32 }) {
  return (
    <svg viewBox="0 0 36 36" width={size} height={size} fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Outer ring */}
      <circle cx="18" cy="18" r="15.5" stroke="#2563eb" strokeWidth="1.4" opacity="0.45" />
      {/* Inner subtle ring */}
      <circle cx="18" cy="18" r="15.5" stroke="#3b82f6" strokeWidth="6" opacity="0.04" />
      {/* ECG / pulse wave — amber */}
      <polyline
        points="2.5,18 7,18 10,10 13.5,26 18,12 21.5,21 24.5,18 33.5,18"
        stroke="#f59e0b" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
        fill="none"
      />
      {/* Active pulse dot — blue, blinks */}
      <circle cx="33.5" cy="18" r="2.2" fill="#3b82f6">
        <animate attributeName="opacity" values="1;0.25;1" dur="1.6s" repeatCount="indefinite" />
      </circle>
      {/* Trailing glow dot */}
      <circle cx="33.5" cy="18" r="4.5" fill="#3b82f6" opacity="0.12">
        <animate attributeName="r" values="3;6;3" dur="1.6s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.12;0;0.12" dur="1.6s" repeatCount="indefinite" />
      </circle>
    </svg>
  )
}

/* ── Feature data ── */
const FEATURES = [
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
        <circle cx="12" cy="12" r="3" /><path d="M3 12h3M18 12h3M12 3v3M12 18v3" />
        <path d="M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
      </svg>
    ),
    title: 'Command Center', tag: 'Live',
    color: '#3b82f6',
    desc: 'Live queue with real-time SA status, hold times, and auto-dispatch tracking across all channels.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
        <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" />
        <circle cx="12" cy="9" r="2.5" />
      </svg>
    ),
    title: 'Fleet Tracking', tag: 'GPS',
    color: '#22c55e',
    desc: 'Live driver positions on Leaflet maps, on-shift detection via AssetHistory, and territory overlays.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ),
    title: 'Response Analytics', tag: 'KPIs',
    color: '#f59e0b',
    desc: 'ETA accuracy, dispatch lag, completion rates, and member satisfaction by garage and driver tier.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
        <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" /><path d="M17.5 14v3M17.5 17h3M14 17.5h3" />
      </svg>
    ),
    title: 'PTA Advisor', tag: 'SLA',
    color: '#a78bfa',
    desc: 'Promised-time entitlement lookups, coverage-type analysis, and cascade P2→P10 routing guidance.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
      </svg>
    ),
    title: 'Dispatch Assist', tag: 'AI',
    color: '#06b6d4',
    desc: 'AI-powered routing suggestions, garage availability panels, and optimizer decision browser.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
        <path d="M12 20V10M18 20V4M6 20v-4" />
      </svg>
    ),
    title: 'Forecasting', tag: 'Forecast',
    color: '#f87171',
    desc: '7-day demand forecasts, weather overlays, staffing gap detection, and priority matrix modeling.',
  },
]

const STATS = [
  { value: 78,   suffix: '%',    label: 'Auto-dispatched' },
  { value: 3,    suffix: '',     label: 'Dispatch channels' },
  { value: 24,   suffix: '/7',   label: 'Live coverage' },
  { value: 18,   suffix: ' min', label: 'Avg response time' },
]

/* ── Animated counter ── */
function Counter({ value, suffix, started }) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    if (!started) return
    let start = 0
    const duration = 1400
    const step = 16
    const inc = value / (duration / step)
    const timer = setInterval(() => {
      start += inc
      if (start >= value) { setDisplay(value); clearInterval(timer) }
      else setDisplay(Math.floor(start))
    }, step)
    return () => clearInterval(timer)
  }, [started, value])
  return <>{display}{suffix}</>
}

/* ── Scroll reveal hook ── */
function useReveal(ref, callback) {
  useEffect(() => {
    if (!ref.current) return
    const obs = new IntersectionObserver(
      entries => entries.forEach(e => {
        if (e.isIntersecting) {
          e.target.classList.add('visible')
          if (callback) callback()
        }
      }),
      { threshold: 0.12 }
    )
    ref.current.querySelectorAll('.reveal').forEach(n => obs.observe(n))
    return () => obs.disconnect()
  }, [ref])
}

/* ── Spotlight card hook ── */
function useSpotlight(ref) {
  useEffect(() => {
    const cards = ref.current?.querySelectorAll('.feature-card')
    if (!cards) return
    const handlers = []
    cards.forEach(card => {
      const fn = e => {
        const rect = card.getBoundingClientRect()
        const x = e.clientX - rect.left
        const y = e.clientY - rect.top
        card.style.setProperty('--mx', `${x}px`)
        card.style.setProperty('--my', `${y}px`)
      }
      card.addEventListener('mousemove', fn)
      handlers.push({ card, fn })
    })
    return () => handlers.forEach(({ card, fn }) => card.removeEventListener('mousemove', fn))
  }, [ref])
}

const goLogin = () => { window.location.href = '/login' }

export default function Landing() {
  const featuresRef = useRef(null)
  const showcaseRef = useRef(null)
  const statsRef = useRef(null)
  const [statsStarted, setStatsStarted] = useState(false)

  useReveal(featuresRef)
  useReveal(showcaseRef)
  useReveal(statsRef, () => setStatsStarted(true))
  useSpotlight(featuresRef)

  const scrollToFeatures = () => document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' })

  return (
    <div className="lp-root">

      {/* ── Noise grain overlay ── */}
      <div className="lp-grain" aria-hidden="true" />

      {/* ── Fixed nav ── */}
      <nav className="lp-nav">
        <a href="/" className="lp-nav-brand" onClick={e => e.preventDefault()}>
          <Logo size={28} />
          <span className="lp-brand-name">Fleet<span>Pulse</span></span>
        </a>
        <div className="lp-nav-right">
          <a
            href="#features"
            className="lp-nav-link"
            onClick={e => { e.preventDefault(); scrollToFeatures() }}
          >
            Features
          </a>
          <button onClick={goLogin} className="lp-nav-cta">
            Sign in
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="lp-hero">
        {/* Globe fills hero */}
        <Suspense fallback={null}>
          <FslGlobe />
        </Suspense>

        {/* Ambient rings behind globe */}
        <div className="lp-ring lp-ring-1" aria-hidden="true" />
        <div className="lp-ring lp-ring-2" aria-hidden="true" />
        <div className="lp-ring lp-ring-3" aria-hidden="true" />

        <div className="lp-hero-content">
          {/* Floating badge */}
          <div className="lp-badge hero-fade hero-fade-0">
            <span className="lp-badge-dot" />
            AAA Field Service Intelligence
          </div>

          {/* Headline */}
          <h1 className="lp-headline hero-fade hero-fade-1">
            Every Member.<br />
            Every Mile.{' '}
            <span className="lp-headline-accent">Covered.</span>
          </h1>

          {/* Globe spacer */}
          <div className="lp-globe-gap" />

          {/* Subheadline */}
          <p className="lp-sub hero-fade hero-fade-2">
            Real-time field service intelligence for AAA dispatchers — live driver positions,
            AI-assisted routing, and response analytics across Fleet, Contractor, and Towbook channels.
          </p>

          {/* CTAs */}
          <div className="lp-ctas hero-fade hero-fade-3">
            <button onClick={goLogin} className="lp-btn-primary">
              Sign in to dashboard
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </button>
            <button onClick={scrollToFeatures} className="lp-btn-ghost">
              Explore features
            </button>
          </div>

          {/* Stats bar */}
          <div className="lp-stats-bar" ref={statsRef}>
            {STATS.map((s, i) => (
              <div key={i} className="lp-stat reveal" style={{ transitionDelay: `${i * 80}ms` }}>
                <div className="lp-stat-value">
                  <Counter value={s.value} suffix={s.suffix} started={statsStarted} />
                </div>
                <div className="lp-stat-label">{s.label}</div>
              </div>
            ))}
          </div>

          {/* Scroll cue */}
          <div className="lp-scroll-cue" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.28)" strokeWidth="2">
              <path d="M7 13l5 5 5-5M7 6l5 5 5-5" />
            </svg>
          </div>
        </div>
      </section>

      {/* ── Visual showcase ── */}
      <section className="lp-showcase-section" ref={showcaseRef}>
        <div className="lp-section-header">
          <div className="lp-glow-line" />
          <h2 className="lp-section-title">Real operations. Real impact.</h2>
          <p className="lp-section-sub">
            From the command center to the roadside — FleetPulse connects every link in the chain.
          </p>
        </div>

        {/* Command center — large product screenshot */}
        <div className="lp-cmd-frame">
          <div className="lp-frame-chrome">
            <span className="lp-chrome-dot lp-dot-red" />
            <span className="lp-chrome-dot lp-dot-amber" />
            <span className="lp-chrome-dot lp-dot-green" />
            <span className="lp-chrome-url">FleetPulse Command Center</span>
          </div>
          <div className="lp-cmd-img-wrap">
            <img
              src="/command-center.jpg"
              alt="AAA Command Center — live dispatch map with 1,026 active requests and 92% SLA compliance"
              className="lp-cmd-img"
            />
            <div className="lp-cmd-overlay" />
          </div>
          {/* Floating stat badges */}
          <div className="lp-cmd-badge lp-cmd-badge-1">
            <span className="lp-live-dot" />
            <div>
              <div className="lp-cmd-badge-val">1,026</div>
              <div className="lp-cmd-badge-lbl">Active requests</div>
            </div>
          </div>
          <div className="lp-cmd-badge lp-cmd-badge-2">
            <div>
              <div className="lp-cmd-badge-val" style={{ color: '#22c55e' }}>92%</div>
              <div className="lp-cmd-badge-lbl">SLA compliance</div>
            </div>
          </div>
          <div className="lp-cmd-badge lp-cmd-badge-3">
            <div>
              <div className="lp-cmd-badge-val">24 min</div>
              <div className="lp-cmd-badge-lbl">Avg ETA</div>
            </div>
          </div>
        </div>

        {/* Two-col: roadside photo + copy */}
        <div className="lp-sc-cols">
          {/* Roadside photo card */}
          <div className="lp-sc-photo-card reveal">
            <img
              src="/roadside-assist.jpg"
              alt="AAA roadside assistance — technician helping a member"
              className="lp-sc-photo"
            />
            <div className="lp-sc-photo-overlay" />
            <div className="lp-sc-photo-badge">
              <span className="lp-sc-live-dot" />
              <div>
                <div className="lp-sc-badge-val">T. Williams — En Route</div>
                <div className="lp-sc-badge-sub">ETA: 11 min · Battery service</div>
              </div>
            </div>
            <div className="lp-sc-label-tag">Roadside Response</div>
          </div>

          {/* Copy block */}
          <div className="lp-sc-copy reveal" style={{ transitionDelay: '100ms' }}>
            <h3 className="lp-sc-title">
              Dispatch faster.<br />Help members sooner.
            </h3>
            <p className="lp-sc-body">
              Live driver positions, AI-assisted routing, and response analytics across
              Fleet, Contractor, and Towbook channels — unified in one intelligence platform.
            </p>
            <ul className="lp-sc-list">
              <li>
                <span className="lp-sc-check">
                  <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="#22c55e" strokeWidth="2" strokeLinecap="round">
                    <path d="M3 8l3.5 3.5L13 4.5" />
                  </svg>
                </span>
                78% of calls auto-dispatched in seconds
              </li>
              <li>
                <span className="lp-sc-check">
                  <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="#22c55e" strokeWidth="2" strokeLinecap="round">
                    <path d="M3 8l3.5 3.5L13 4.5" />
                  </svg>
                </span>
                3 dispatch channels unified in one view
              </li>
              <li>
                <span className="lp-sc-check">
                  <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="#22c55e" strokeWidth="2" strokeLinecap="round">
                    <path d="M3 8l3.5 3.5L13 4.5" />
                  </svg>
                </span>
                Real-time GPS tracking with on-shift detection
              </li>
              <li>
                <span className="lp-sc-check">
                  <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="#22c55e" strokeWidth="2" strokeLinecap="round">
                    <path d="M3 8l3.5 3.5L13 4.5" />
                  </svg>
                </span>
                AI-powered routing with 7-day demand forecasts
              </li>
            </ul>
            <button onClick={goLogin} className="lp-btn-primary" style={{ marginTop: 28 }}>
              See live operations
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </button>
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section id="features" className="lp-features-section" ref={featuresRef}>
        <div className="lp-section-header">
          <div className="lp-glow-line" />
          <h2 className="lp-section-title">Built for field service operations</h2>
          <p className="lp-section-sub">
            Every tool a dispatcher needs — from live queue management to multi-day forecasting.
          </p>
        </div>

        <div className="lp-feature-grid">
          {FEATURES.map((f, i) => (
            <button
              key={i}
              className="feature-card reveal"
              onClick={goLogin}
              style={{ '--accent': f.color, transitionDelay: `${i * 60}ms` }}
            >
              <div className="fc-spotlight" />
              <div className="fc-top">
                <div className="fc-icon" style={{ '--icon-color': f.color }}>
                  {f.icon}
                </div>
                <span className="fc-tag" style={{ '--tag-color': f.color }}>{f.tag}</span>
              </div>
              <h3 className="fc-title">{f.title}</h3>
              <p className="fc-desc">{f.desc}</p>
              <div className="fc-cta" style={{ color: f.color }}>
                Open feature
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </div>
            </button>
          ))}
        </div>
      </section>

      {/* ── CTA band ── */}
      <section className="lp-cta-band">
        <div className="lp-cta-band-bg" aria-hidden="true" />
        <div className="lp-cta-band-inner">
          <div className="lp-cta-band-text">
            <h2 className="lp-cta-band-title">Ready to dispatch smarter?</h2>
            <p className="lp-cta-band-sub">
              Live data from 3 dispatch channels, real-time driver tracking, and AI-assisted routing — all in one place.
            </p>
          </div>
          <button onClick={goLogin} className="lp-btn-primary">
            Sign in to dashboard
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="lp-footer">
        <div className="lp-footer-brand">
          <Logo size={18} />
          <span>FleetPulse &middot; AAA Field Service Intelligence</span>
        </div>
        <span className="lp-footer-copy">Internal tool &middot; {new Date().getFullYear()}</span>
      </footer>

    </div>
  )
}
