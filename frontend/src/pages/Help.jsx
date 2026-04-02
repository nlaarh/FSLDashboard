import { useState, useEffect } from 'react'
import {
  BookOpen, Calculator, Database, Target, ChevronDown, ChevronUp,
  ShieldCheck, AlertTriangle, Truck, HelpCircle, Workflow, ArrowLeft,
} from 'lucide-react'
import { clsx } from 'clsx'
import { motion, AnimatePresence } from 'framer-motion'

// ── Split child components ───────────────────────────────────────────────────
import HowItWorksSection from '../components/HelpHowItWorks'
import { HowItWorksTopics567 } from '../components/HelpGuides'
import { OverviewSection, ScoringSection } from '../components/HelpGuides'
import { MetricsSection, RulesSection, OpsRecommendationsSection, QualitySection } from '../components/HelpContent'
import DataSection from '../components/HelpData'

/* ── Framer Motion helpers ── */
const fadeUp = { hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0 } }
const stagger = (staggerChildren = 0.06) => ({
  hidden: {},
  show: { transition: { staggerChildren } },
})

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION DEFINITIONS
// ═══════════════════════════════════════════════════════════════════════════════

const SECTIONS = [
  { id: 'howitworks', label: 'How It Works',          icon: Workflow,       desc: 'End-to-end operations guide — territories, dispatch, fleet vs contractors, scoring, and the full call lifecycle.' },
  { id: 'overview',   label: 'Dispatch Manager Guide', icon: BookOpen,      desc: 'Page-by-page guide — what to look for, how to read the data, and when to take action.' },
  { id: 'metrics',    label: 'Metric Definitions',   icon: Calculator,     desc: 'Every metric — what it measures, how it is calculated, and which Salesforce fields are used.' },
  { id: 'scoring',    label: 'How Garages Are Rated', icon: Target,         desc: 'Plain English guide to how the system scores and grades each garage from A to F.' },
  { id: 'data',       label: 'Data & Model',         icon: Database,       desc: 'Searchable field dictionary and entity-relationship diagram — all Salesforce objects in one place.' },
  { id: 'quality',    label: 'Data Quality',         icon: ShieldCheck,    desc: 'Live field-level quality audit with severity ratings and recommendations.' },
  { id: 'rules',      label: 'Business Rules',       icon: AlertTriangle,  desc: 'Key filters, guardrails, and exclusions that affect metric calculations.' },
  { id: 'ops',        label: 'Ops Recommendations',   icon: Truck,          desc: 'How to improve driver assignment — Fleet vs Towbook challenges and actionable fixes.' },
]

// ═══════════════════════════════════════════════════════════════════════════════
// LANDING CARDS — shown when no section is selected
// ═══════════════════════════════════════════════════════════════════════════════

function LandingCards({ onSelect }) {
  return (
    <div>
      <motion.div className="text-center mb-8" initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
        <HelpCircle className="w-10 h-10 text-brand-400 mx-auto mb-3" />
        <h1 className="text-2xl font-bold text-white mb-2">Help Center</h1>
        <p className="text-sm text-slate-400 max-w-lg mx-auto">
          Everything you need to understand FSL App — metrics, scoring, data fields, quality audits, and business rules.
        </p>
      </motion.div>
      <motion.div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 max-w-5xl mx-auto"
        variants={stagger(0.07)} initial="hidden" animate="show">
        {SECTIONS.map(s => (
          <motion.button key={s.id} onClick={() => onSelect(s.id)} variants={fadeUp}
            transition={{ type: 'spring', stiffness: 260, damping: 22 }}
            whileHover={{ scale: 1.03, y: -3 }} whileTap={{ scale: 0.97 }}
            className="group glass rounded-xl p-5 border border-slate-700/20 hover:border-brand-500/40 transition-colors text-left">
            <div className="w-10 h-10 rounded-xl bg-brand-600/10 border border-brand-500/20 flex items-center justify-center mb-3 group-hover:bg-brand-600/20 transition-colors">
              <s.icon className="w-5 h-5 text-brand-400" />
            </div>
            <h3 className="font-semibold text-sm text-white mb-1">{s.label}</h3>
            <p className="text-[11px] text-slate-500 leading-relaxed">{s.desc}</p>
          </motion.button>
        ))}
      </motion.div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT — Horizontal Tabs + Landing Cards
// ═══════════════════════════════════════════════════════════════════════════════

export default function Help() {
  const [activeSection, setActiveSection] = useState(null) // null = landing
  const [dictionary, setDictionary] = useState(null)

  useEffect(() => {
    fetch('/data/fsl-dictionary.json')
      .then(r => r.json())
      .then(setDictionary)
      .catch(() => {})
  }, [])

  const renderSection = () => {
    switch (activeSection) {
      case 'howitworks': return (
        <HowItWorksSection
          renderTopics567={({ expandedTopic, toggle }) => (
            <HowItWorksTopics567 expandedTopic={expandedTopic} toggle={toggle} />
          )}
        />
      )
      case 'overview':   return <OverviewSection />
      case 'metrics':    return <MetricsSection />
      case 'scoring':    return <ScoringSection />
      case 'data':       return <DataSection data={dictionary} />
      case 'quality':    return <QualitySection />
      case 'rules':      return <RulesSection />
      case 'ops':        return <OpsRecommendationsSection />
      default:           return <LandingCards onSelect={setActiveSection} />
    }
  }

  return (
    <div style={{ minHeight: 'calc(100vh - 120px)' }}>
      {/* ── Horizontal Tab Bar ── */}
      {activeSection && (
        <div className="flex items-center gap-1 mb-6 pb-3 border-b border-slate-800/50 overflow-x-auto">
          <button onClick={() => setActiveSection(null)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-500 hover:text-white hover:bg-slate-800 transition-all shrink-0 mr-1">
            <ArrowLeft className="w-3.5 h-3.5" />
            <span className="text-xs">All Topics</span>
          </button>
          <div className="w-px h-5 bg-slate-800 mr-1" />
          {SECTIONS.map(s => (
            <button key={s.id} onClick={() => setActiveSection(s.id)}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all whitespace-nowrap shrink-0',
                activeSection === s.id
                  ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/50 border border-transparent'
              )}>
              <s.icon className="w-3.5 h-3.5" />
              {s.label}
            </button>
          ))}
        </div>
      )}

      {/* ── Content ── */}
      <AnimatePresence mode="wait">
        <motion.div key={activeSection || 'landing'}
          initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.25 }}>
          {renderSection()}
        </motion.div>
      </AnimatePresence>

      {/* Chat is now global in Layout */}
    </div>
  )
}
