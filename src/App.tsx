import { useEffect, useMemo, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import AnimatedCounter from "./components/AnimatedCounter"
import { GooeyNav } from "./components/GooeyNav"

type IconName = "upload" | "play" | "file" | "check" | "chevron" | "clock" | "download" | "menu" | "close" | "activity"

function Icon({ name, size = 18 }: { name: IconName size?: number }) {
  const paths: Record<IconName, React.ReactNode> = {
    upload: (
      <>
        <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" />
        <path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
      </>
    ),
    play: <path d="m8 5 11 7-11 7V5Z" />,
    file: (
      <>
        <path d="M6 2h8l4 4v16H6V2Z" />
        <path d="M14 2v5h5M9 12h6M9 16h6" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    chevron: <path d="m9 18 6-6-6-6" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    download: (
      <>
        <path d="M12 3v12m0 0 4-4m-4 4-4-4" />
        <path d="M5 20h14" />
      </>
    ),
    menu: <path d="M4 7h16M4 12h16M4 17h16" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    activity: <path d="M3 12h4l2-7 4 14 2-7h6" />,
  }
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
    >
      {paths[name]}
    </svg>
  )
}

function LiveCounter({
  target,
  decimals = 0,
  suffix = "",
  duration,
}: {
  target: number
  decimals?: number
  suffix?: string
  duration: number
}) {
  const [value, setValue] = useState(0)

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setValue(target))
    return () => window.cancelAnimationFrame(frame)
  }, [target])

  return (
    <AnimatedCounter
      className="counter-value"
      value={value}
      decimals={decimals}
      suffix={suffix}
      duration={duration}
    />
  )
}

const signalRows = [
  ["LSHH-101", "DI", "Area 01", "CAB-01", "CIOC-01", "BP-01", "01"],
  ["PT-204", "AI", "Area 01", "CAB-01", "CIOC-01", "BP-02", "05"],
  ["XV-301-O", "DO", "Area 02", "CAB-01", "CIOC-02", "BP-01", "11"],
  ["FT-402", "HART_AI", "Area 02", "CAB-02", "CIOC-01", "BP-03", "04"],
  ["FV-402", "AO", "Area 02", "CAB-02", "CIOC-01", "BP-04", "08"],
  ["ZS-503", "DI", "Area 03", "CAB-02", "CIOC-02", "BP-01", "13"],
  ["TT-604", "AI", "Area 03", "CAB-03", "CIOC-01", "BP-02", "07"],
  ["HS-705", "DI", "Area 04", "CAB-03", "CIOC-02", "BP-02", "15"],
]

const typeData = [
  { name: "Digital Input", code: "DI", count: 80, pct: 40, color: "#3b82f6" },
  { name: "Analog Input", code: "AI", count: 50, pct: 25, color: "#06b6d4" },
  { name: "Digital Output", code: "DO", count: 30, pct: 15, color: "#8b5cf6" },
  { name: "Analog Output", code: "AO", count: 20, pct: 10, color: "#f59e0b" },
  {
    name: "HART Analog Input",
    code: "HART_AI",
    count: 10,
    pct: 5,
    color: "#22c55e",
  },
  {
    name: "Other / Specialty",
    code: "OTHER",
    count: 10,
    pct: 5,
    color: "#64748b",
  },
]

const rules = [
  [
    "Signal Type Isolation",
    "Prevents mixed signal types within a CHARM carrier.",
    "One type per CHARM",
    true,
  ],
  [
    "Spare Capacity",
    "Maintains engineered headroom for future field additions.",
    "15% minimum",
    true,
  ],
  [
    "Max Fill Rate",
    "Limits the usable capacity of each CHARM carrier.",
    "85% maximum",
    true,
  ],
  [
    "Area Grouping",
    "Keeps signals from the same process area together.",
    "Priority grouping",
    true,
  ],
  [
    "Last Baseplate Reserve",
    "Reserves the final baseplate on each CIOC for expansion.",
    "BP-08 reserved",
    false,
  ],
]

const navItems = [
  ["Allocate", "allocate"],
  ["Results", "results"],
  ["Rules", "rules"],
  ["Revisions", "revisions"],
  ["Exceptions", "exceptions"],
]

const builtInRuleOptions = [
  {
    id: "type-isolation",
    name: "Signal Type Isolation",
    description: "Keep the selected signal type on dedicated CHARM carriers.",
    defaultValue: "Dedicated carrier",
  },
  {
    id: "max-fill",
    name: "Maximum CHARM Fill",
    description: "Set the maximum permitted carrier utilization.",
    defaultValue: "85%",
  },
  {
    id: "spare-capacity",
    name: "Minimum Spare Capacity",
    description: "Reserve expansion capacity for the selected signals.",
    defaultValue: "15%",
  },
  {
    id: "area-grouping",
    name: "Process Area Grouping",
    description: "Keep signals from the same process area together.",
    defaultValue: "Strict",
  },
  {
    id: "cabinet-assignment",
    name: "Preferred Cabinet",
    description: "Route matching signals to a preferred cabinet first.",
    defaultValue: "CAB-01",
  },
  {
    id: "safety-segregation",
    name: "Safety Signal Segregation",
    description: "Separate safety-related signals from standard control I/O.",
    defaultValue: "SIS isolated",
  },
  {
    id: "custom",
    name: "Custom Engineering Rule…",
    description: "Create a project-specific condition for matching signals.",
    defaultValue: "Enter custom condition",
  },
]

type AssignedRule = {
  id: number
  template: string
  target: string
  condition: string
}

export default function App() {
  const [activeNav, setActiveNav] = useState("Allocate")
  const [mobileOpen, setMobileOpen] = useState(false)
  const [loaded, setLoaded] = useState(true)
  const [dragging, setDragging] = useState(false)
  const [running, setRunning] = useState(false)
  const [hasResults, setHasResults] = useState(true)
  const [tab, setTab] = useState("Allocation Table")
  const [expanded, setExpanded] = useState<number[]>([0])
  const [compare, setCompare] = useState(false)
  const [scroll, setScroll] = useState(0)
  const [spare, setSpare] = useState(15)
  const [fill, setFill] = useState(85)
  const [toggles, setToggles] = useState([true, true, false])
  const [ruleTemplate, setRuleTemplate] = useState(builtInRuleOptions[0].id)
  const [ruleTarget, setRuleTarget] = useState("All signals")
  const [ruleCondition, setRuleCondition] = useState(
    builtInRuleOptions[0].defaultValue,
  )
  const [assignedRules, setAssignedRules] = useState<AssignedRule[]>([])

  useEffect(() => {
    const onScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight
      setScroll(max > 0 ? window.scrollY / max : 0)
    }
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])

  const runAllocation = () => {
    if (!loaded || running) return
    setRunning(true)
    setHasResults(false)
    window.setTimeout(() => {
      setRunning(false)
      setHasResults(true)
      document
        .querySelector("#results")
        ?.scrollIntoView({ behavior: "smooth", block: "start" })
    }, 1200)
  }

  const handleNav = (label: string, id: string) => {
    setActiveNav(label)
    setMobileOpen(false)
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  const selectRuleTemplate = (templateId: string) => {
    setRuleTemplate(templateId)
    const template = builtInRuleOptions.find((item) => item.id === templateId)
    if (template) setRuleCondition(template.defaultValue)
  }

  const addAssignedRule = () => {
    const template = builtInRuleOptions.find((item) => item.id === ruleTemplate)
    if (!template || !ruleCondition.trim()) return
    setAssignedRules((current) => [
      ...current,
      {
        id: Date.now(),
        template: template.name,
        target: ruleTarget,
        condition: ruleCondition.trim(),
      },
    ])
  }

  const tabContent = useMemo(() => {
    if (tab === "Hierarchy")
      return <Hierarchy expanded={expanded} setExpanded={setExpanded} />
    if (tab === "Type Breakdown") return <TypeBreakdown />
    if (tab === "Audit Trail") return <AuditTrail />
    return <AllocationTable />
  }, [tab, expanded])

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="nav-wrap">
          <button
            className="brand"
            onClick={() => handleNav("Allocate", "allocate")}
            aria-label="IO Signal Sudoku home"
          >
            <span className="brand-grid">
              {[0, 1, 2, 3].map((n) => (
                <i key={n} />
              ))}
            </span>
            <span>IO Sudoku</span>
          </button>
          <GooeyNav
            className="desktop-nav"
            items={navItems.map(([label]) => label)}
            value={navItems.findIndex(([label]) => label === activeNav)}
            size="xs"
            activeColor="#1d4ed8"
            separation={11}
            onChange={(index) =>
              handleNav(navItems[index][0], navItems[index][1])
            }
          />
          <div className="event-tag">
            <span /> VIT Code Apex 3.0 <b>·</b> Track 1 <b>·</b> Problem 2
          </div>
          <button
            className="mobile-trigger"
            onClick={() => setMobileOpen(!mobileOpen)}
            aria-label="Toggle navigation"
          >
            <Icon name={mobileOpen ? "close" : "menu"} />
          </button>
        </div>
        {mobileOpen && (
          <nav className="mobile-nav">
            {navItems.map(([label, id]) => (
              <button key={id} onClick={() => handleNav(label, id)}>
                {label}
              </button>
            ))}
          </nav>
        )}
      </header>

      <aside className="rail" aria-hidden="true">
        <span className="rail-line" />
        <span className="rail-dot" style={{ top: `${scroll * 100}%` }} />
        {navItems.map(([label, id], i) => (
          <button
            key={id}
            style={{ top: `${i * 25}%` }}
            onClick={() => handleNav(label, id)}
          >
            <span>{label}</span>
          </button>
        ))}
      </aside>

      <main>
        <section className="hero content" id="allocate">
          <motion.div
            className="hero-content"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", stiffness: 120, damping: 20 }}
          >
            <div className="eyebrow">
              <span className="live-dot" /> DCS I/O ALLOCATION ENGINE{" "}
              <em>v3.0</em>
            </div>
            <h1>
              IO Signal <span>Sudoku</span>
            </h1>
            <p className="hero-copy">
              Upload an Excel I/O schedule. The engine allocates every signal to
              its exact Cabinet → CIOC → Baseplate → CHARM slot with full rule
              enforcement and audit traceability.
            </p>
          </motion.div>
          <div className="stats">
            {[
              [10000, "+", "Signals"],
              [27, "", "Cabinets"],
              [10368, "", "I/O Channels"],
              [100, "%", "Traceable"],
            ].map(([value, suffix, label], index) => (
              <div className="stat" key={label}>
                <LiveCounter
                  target={Number(value)}
                  suffix={suffix}
                  duration={0.75 + index * 0.1}
                />
                <span>{label}</span>
              </div>
            ))}
          </div>
        </section>

        <div className="divider" />

        <section
          className="work-grid content"
          aria-label="Schedule configuration"
        >
          <article className="card input-card">
            <div className="section-heading">
              <div>
                <span className="kicker">01 / INPUT</span>
                <h2>Schedule Input</h2>
              </div>
              {loaded && (
                <span className="status success">
                  <i /> Ready
                </span>
              )}
            </div>
            {!loaded ? (
              <div
                className={`dropzone ${dragging ? "dragging" : ""}`}
                onDragEnter={(e) => {
                  e.preventDefault()
                  setDragging(true)
                }}
                onDragOver={(e) => e.preventDefault()}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragging(false)
                  setLoaded(true)
                }}
              >
                <div className="upload-icon">
                  <Icon name="upload" size={24} />
                </div>
                <h3>Drop your I/O schedule here</h3>
                <p>.xlsx or .csv · Up to 10,000 signals</p>
                <label className="secondary-button">
                  Browse files
                  <input
                    type="file"
                    accept=".xlsx,.csv"
                    onChange={() => setLoaded(true)}
                  />
                </label>
                <span className="or">OR</span>
                <button className="text-button" onClick={() => setLoaded(true)}>
                  Load 200-signal demo
                </button>
              </div>
            ) : (
              <>
                <div className="file-summary">
                  <span className="file-icon">
                    <Icon name="file" size={20} />
                  </span>
                  <div>
                    <strong>io_schedule_demo.xlsx</strong>
                    <small>200 signals · 18.4 KB</small>
                  </div>
                  <span className="verified">
                    <Icon name="check" size={14} /> Validated
                  </span>
                </div>
                <div className="badges">
                  {typeData.slice(0, 5).map((item) => (
                    <span
                      key={item.code}
                      className={`badge badge-${item.code.toLowerCase()}`}
                    >
                      {item.code}: {item.count}
                    </span>
                  ))}
                </div>
                <div className="table-scroll preview">
                  <table>
                    <thead>
                      <tr>
                        <th>Tag</th>
                        <th>Type</th>
                        <th>Area</th>
                        <th>Target</th>
                      </tr>
                    </thead>
                    <tbody>
                      {signalRows.slice(0, 5).map((r) => (
                        <tr key={r[0]}>
                          <td>{r[0]}</td>
                          <td>
                            <span className="mini-type">{r[1]}</span>
                          </td>
                          <td>{r[2]}</td>
                          <td>
                            {r[3]} / {r[4]}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button
                  className="clear-button"
                  onClick={() => {
                    setLoaded(false)
                    setHasResults(false)
                  }}
                >
                  Clear and upload different file
                </button>
              </>
            )}
          </article>

          <article className="card rules-card">
            <div className="section-heading">
              <div>
                <span className="kicker">02 / CONFIGURE</span>
                <h2>Allocation Rules</h2>
              </div>
              <span className="profile-label">PROFILE: STANDARD</span>
            </div>
            <div className="slider-field">
              <div>
                <label htmlFor="spare">Spare capacity margin</label>
                <output>{spare}%</output>
              </div>
              <input
                id="spare"
                type="range"
                min="5"
                max="30"
                value={spare}
                onChange={(e) => setSpare(Number(e.target.value))}
              />
              <div className="range-labels">
                <span>5%</span>
                <span>30%</span>
              </div>
            </div>
            <div className="slider-field">
              <div>
                <label htmlFor="fill">Max CHARM fill</label>
                <output>{fill}%</output>
              </div>
              <input
                id="fill"
                type="range"
                min="60"
                max="100"
                value={fill}
                onChange={(e) => setFill(Number(e.target.value))}
              />
              <div className="range-labels">
                <span>60%</span>
                <span>100%</span>
              </div>
            </div>
            <div className="toggle-list">
              {[
                "Isolate signal types per CHARM",
                "Group signals by process area",
                "Reserve last baseplate per CIOC",
              ].map((label, i) => (
                <div className="toggle-row" key={label}>
                  <div>
                    <strong>{label}</strong>
                    <small>
                      {
                        [
                          "Prevents mixed I/O carrier types",
                          "Minimizes cross-area wiring",
                          "Maintains future expansion capacity",
                        ][i]
                      }
                    </small>
                  </div>
                  <button
                    role="switch"
                    aria-checked={toggles[i]}
                    className={`switch ${toggles[i] ? "on" : ""}`}
                    onClick={() =>
                      setToggles(toggles.map((v, j) => (j === i ? !v : v)))
                    }
                  >
                    <span />
                  </button>
                </div>
              ))}
            </div>
            <button
              className="run-button"
              disabled={!loaded || running}
              onClick={runAllocation}
            >
              {running ? (
                <>
                  <span className="spinner" /> Allocating 200 signals...
                </>
              ) : (
                <>
                  <Icon name="play" size={17} /> Run Allocation Engine
                </>
              )}
            </button>
            <p className="run-note">
              <span /> Rules validated · Estimated runtime &lt; 2 sec
            </p>
          </article>
        </section>

        <AnimatePresence>
          {hasResults && (
            <motion.section
              className="results content"
              id="results"
              initial={{ opacity: 0, y: 26 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
              transition={{ type: "spring", stiffness: 110, damping: 20 }}
            >
              <div className="section-title-row">
                <div>
                  <span className="kicker">03 / OUTPUT</span>
                  <h2>Allocation Results</h2>
                  <p>Run #0042 · Completed in 1.24 seconds</p>
                </div>
                <span className="status success">
                  <i /> Allocation complete
                </span>
              </div>
              <div className="metrics">
                {[
                  [200, 0, "", "Total Signals", "100% ingested"],
                  [200, 0, "", "Allocated", "0 unassigned"],
                  [3, 0, "", "Cabinets Used", "of 27 available"],
                  [15, 0, "", "CHARMs Used", "of 648 available"],
                  [78.4, 1, "%", "Fill Rate", "Within target"],
                ].map(([value, decimals, suffix, label, note], i) => (
                  <motion.div
                    className="metric"
                    key={String(label)}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.07 }}
                  >
                    <span className="metric-icon">0{i + 1}</span>
                    <LiveCounter
                      target={Number(value)}
                      decimals={Number(decimals)}
                      suffix={suffix}
                      duration={0.75 + i * 0.08}
                    />
                    <b>{label}</b>
                    <small className={i === 4 ? "good" : ""}>{note}</small>
                  </motion.div>
                ))}
              </div>
              <div className="results-panel">
                <div className="tabs" role="tablist">
                  {[
                    "Allocation Table",
                    "Hierarchy",
                    "Type Breakdown",
                    "Audit Trail",
                  ].map((name) => (
                    <button
                      role="tab"
                      aria-selected={tab === name}
                      className={tab === name ? "active" : ""}
                      onClick={() => setTab(name)}
                      key={name}
                    >
                      {name}
                    </button>
                  ))}
                </div>
                <AnimatePresence mode="wait">
                  <motion.div
                    className="tab-content"
                    key={tab}
                    initial={{ opacity: 0, x: 12 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -12 }}
                    transition={{ duration: 0.2 }}
                  >
                    {tabContent}
                  </motion.div>
                </AnimatePresence>
              </div>
            </motion.section>
          )}
        </AnimatePresence>

        <div className="divider" />

        <section className="content rules-section" id="rules">
          <div className="section-title-row">
            <div>
              <span className="kicker">04 / GOVERNANCE</span>
              <h2>Active Rule Profile</h2>
              <p>Rules applied to allocation run #0042</p>
            </div>
            <button className="outline-button">Manage profiles</button>
          </div>
          <div className="rule-list">
            {rules.map(([name, description, detail, active], i) => (
              <div className="rule-card" key={String(name)}>
                <span className="rule-number">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div>
                  <strong>{String(name)}</strong>
                  <p>{String(description)}</p>
                </div>
                <code>{String(detail)}</code>
                <span className={`status ${active ? "success" : "off"}`}>
                  <i />
                  {active ? "Active" : "Off"}
                </span>
              </div>
            ))}
          </div>
          <div className="rule-builder">
            <div className="rule-builder-head">
              <div>
                <span className="kicker">RULE ASSIGNMENT</span>
                <h3>Add a signal condition</h3>
                <p>
                  Select a built-in engineering rule, choose which signals it
                  applies to, then assign its condition.
                </p>
              </div>
              <span className="profile-label">BUILT-IN LIBRARY</span>
            </div>
            <div className="rule-builder-grid">
              <label className="select-field">
                <span>Built-in rule</span>
                <select
                  value={ruleTemplate}
                  onChange={(event) => selectRuleTemplate(event.target.value)}
                >
                  {builtInRuleOptions.map((option) => (
                    <option value={option.id} key={option.id}>
                      {option.name}
                    </option>
                  ))}
                </select>
                <small>
                  {
                    builtInRuleOptions.find(
                      (option) => option.id === ruleTemplate,
                    )?.description
                  }
                </small>
              </label>
              <label className="select-field">
                <span>Apply to signals</span>
                <select
                  value={ruleTarget}
                  onChange={(event) => setRuleTarget(event.target.value)}
                >
                  <option>All signals</option>
                  <option>DI — Digital Input</option>
                  <option>DO — Digital Output</option>
                  <option>AI — Analog Input</option>
                  <option>AO — Analog Output</option>
                  <option>HART_AI — HART Analog Input</option>
                  <option>SIS — Safety signals</option>
                </select>
                <small>Signal type or classification to match.</small>
              </label>
              <label className="select-field">
                <span>Assigned condition</span>
                <input
                  value={ruleCondition}
                  onChange={(event) => setRuleCondition(event.target.value)}
                  placeholder="Enter a condition"
                />
                <small>Adjust the default value when required.</small>
              </label>
              <button className="add-rule-button" onClick={addAssignedRule}>
                <span>+</span> Add rule
              </button>
            </div>
            <AnimatePresence initial={false}>
              {assignedRules.length > 0 && (
                <motion.div
                  className="assigned-rules"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                >
                  <div className="assigned-rules-title">
                    <span>NEW CONDITIONS</span>
                    <b>{assignedRules.length} configured</b>
                  </div>
                  {assignedRules.map((rule) => (
                    <motion.div
                      className="assigned-rule"
                      key={rule.id}
                      layout
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: 10 }}
                    >
                      <span className="rule-link-dot" />
                      <div>
                        <strong>{rule.template}</strong>
                        <p>
                          IF <b>{rule.target}</b> → {rule.condition}
                        </p>
                      </div>
                      <span className="status success">
                        <i /> Pending
                      </span>
                      <button
                        aria-label={`Remove ${rule.template}`}
                        onClick={() =>
                          setAssignedRules((current) =>
                            current.filter((item) => item.id !== rule.id),
                          )
                        }
                      >
                        ×
                      </button>
                    </motion.div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </section>

        <section className="content history" id="revisions">
          <div className="section-title-row">
            <div>
              <span className="kicker">05 / AUDITABILITY</span>
              <h2>Revision History</h2>
              <p>Immutable allocation run history</p>
            </div>
            <button
              className="outline-button"
              onClick={() => setCompare(!compare)}
            >
              {compare ? "Hide comparison" : "Compare last two runs"}
            </button>
          </div>
          <AnimatePresence>
            {compare && (
              <motion.div
                className="delta-card"
                initial={{ opacity: 0, height: 0, y: -8 }}
                animate={{ opacity: 1, height: "auto", y: 0 }}
                exit={{ opacity: 0, height: 0, y: -8 }}
                transition={{ type: "spring", stiffness: 170, damping: 24 }}
              >
                <div>
                  <span>ALLOCATED Δ</span>
                  <strong>+12</strong>
                  <small>188 → 200 signals</small>
                </div>
                <div>
                  <span>ISSUES Δ</span>
                  <strong className="green">−3</strong>
                  <small>5 → 2 exceptions</small>
                </div>
                <div>
                  <span>SPARE MARGIN</span>
                  <strong>+2.0%</strong>
                  <small>13% → 15% target</small>
                </div>
                <div className="delta-summary">
                  <Icon name="activity" />
                  <span>
                    Run #0042 improved allocation coverage by <b>6.4%</b>
                  </span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          <div className="history-card">
            <div className="history-header">
              <span>RUN</span>
              <span>TIMESTAMP</span>
              <span>SIGNALS</span>
              <span>FILL RATE</span>
              <span>STATUS</span>
            </div>
            {[
              ["#0042", "Today, 14:32:08", "200", "78.4%", "Clean"],
              ["#0041", "Today, 11:18:42", "188", "76.1%", "3 issues"],
              ["#0040", "12 Jun 2025, 16:04:11", "188", "74.8%", "Clean"],
              ["#0039", "11 Jun 2025, 09:22:54", "164", "71.2%", "2 issues"],
            ].map((r, i) => (
              <div className="history-row" key={r[0]}>
                <strong>
                  {r[0]}
                  {i === 0 && <small>LATEST</small>}
                </strong>
                <span>
                  <Icon name="clock" size={14} />
                  {r[1]}
                </span>
                <span>{r[2]}</span>
                <span>{r[3]}</span>
                <span
                  className={`status ${
                    r[4] === "Clean" ? "success" : "warning"
                  }`}
                >
                  <i />
                  {r[4]}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="content exceptions" id="exceptions">
          <div className="section-title-row">
            <div>
              <span className="kicker">06 / RESOLUTION</span>
              <h2>Exceptions &amp; TQ Log</h2>
              <p>Items requiring engineering review</p>
            </div>
            <button className="outline-button">
              <Icon name="download" size={16} /> Export TQ log
            </button>
          </div>
          <div className="issue-summary">
            <div>
              <strong className="red">0</strong>
              <span>Errors</span>
              <small>Blocking allocation</small>
            </div>
            <div>
              <strong className="amber">2</strong>
              <span>Warnings</span>
              <small>Review recommended</small>
            </div>
            <div>
              <strong>1</strong>
              <span>Technical Query</span>
              <small>Pending response</small>
            </div>
          </div>
          <div className="issue-list">
            <div className="issue warning-row">
              <span className="issue-code">WRN-014</span>
              <div>
                <strong>Spare margin below target on CAB-03 / CIOC-02</strong>
                <p>
                  Current spare capacity is 12.5%, below the configured 15%
                  threshold. Consider moving 2 DI signals.
                </p>
              </div>
              <span className="badge warning">CAPACITY</span>
            </div>
            <div className="issue info-row">
              <span className="issue-code">TQ-008</span>
              <div>
                <strong>Signal type clarification required for XA-901</strong>
                <p>
                  Source schedule lists type as “SPECIAL”. Confirm whether a DI
                  CHARM is acceptable before IFC release.
                </p>
              </div>
              <span className="badge info">OPEN TQ</span>
            </div>
          </div>
        </section>
      </main>

      <footer>
        <span className="footer-logo">
          {[0, 1, 2, 3].map((n) => (
            <i key={n} />
          ))}
        </span>
        <p>
          Holy Quadrinity <b>·</b> VIT Code Apex 3.0 <b>·</b> Track 1 — Problem
          2 <b>·</b> IO Signal Sudoku
        </p>
      </footer>
    </div>
  )
}

function AllocationTable() {
  return (
    <>
      <div className="table-toolbar">
        <span>Showing 8 of 200 allocated signals</span>
        <button>
          <Icon name="download" size={15} /> Export XLSX
        </button>
      </div>
      <div className="table-scroll">
        <table className="allocation-table">
          <thead>
            <tr>
              {[
                "Signal Tag",
                "Type",
                "Process Area",
                "Cabinet",
                "CIOC",
                "Baseplate",
                "Slot",
              ].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {signalRows.map((r) => (
              <tr key={r[0]}>
                {r.map((cell, i) => (
                  <td key={i}>
                    {i === 1 ? <span className="mini-type">{cell}</span> : cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-footer">
        <span>
          <i /> All 200 signals allocated successfully
        </span>
        <span>Page 1 of 25</span>
      </div>
    </>
  )
}

function Hierarchy({
  expanded,
  setExpanded,
}: {
  expanded: number[]
  setExpanded: (v: number[]) => void
}) {
  const cabinets = [
    [
      "CAB-01",
      "88 signals",
      [
        ["CIOC-01", "48 signals · 4 CHARMs"],
        ["CIOC-02", "40 signals · 3 CHARMs"],
      ],
    ],
    [
      "CAB-02",
      "72 signals",
      [
        ["CIOC-01", "40 signals · 3 CHARMs"],
        ["CIOC-02", "32 signals · 2 CHARMs"],
      ],
    ],
    [
      "CAB-03",
      "40 signals",
      [
        ["CIOC-01", "24 signals · 2 CHARMs"],
        ["CIOC-02", "16 signals · 1 CHARM"],
      ],
    ],
  ] as const
  return (
    <div className="tree">
      {cabinets.map((cab, i) => (
        <div className="tree-group" key={cab[0]}>
          <button
            onClick={() =>
              setExpanded(
                expanded.includes(i)
                  ? expanded.filter((n) => n !== i)
                  : [...expanded, i],
              )
            }
          >
            <Icon name="chevron" size={16} />
            <span className="cab-dot" />
            <strong>{cab[0]}</strong>
            <span>{cab[1]}</span>
            <em>{i + 5} CHARMs</em>
          </button>
          {expanded.includes(i) && (
            <div className="tree-children">
              {cab[2].map((child, j) => (
                <div key={child[0]}>
                  <span className={`cioc-dot dot-${j}`} />
                  <strong>{child[0]}</strong>
                  <span>{child[1]}</span>
                  <small>{j === 0 ? "78%" : "81%"} fill</small>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function TypeBreakdown() {
  return (
    <div className="breakdown">
      <div className="breakdown-head">
        <div>
          <strong>200</strong>
          <span>Total signals</span>
        </div>
        <p>Distribution by I/O signal type</p>
      </div>
      {typeData.map((item) => (
        <div className="progress-row" key={item.code}>
          <div>
            <span className="color-dot" style={{ background: item.color }} />
            <strong>{item.name}</strong>
            <code>{item.code}</code>
            <b>{item.count}</b>
            <em>{item.pct}%</em>
          </div>
          <div className="progress-track">
            <span style={{ width: `${item.pct}%`, background: item.color }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function AuditTrail() {
  return (
    <div className="audit-list">
      {[
        [
          "14:32:08.421",
          "Allocation complete",
          "200/200 signals assigned · 0 blocking errors",
          "success",
        ],
        [
          "14:32:08.106",
          "Capacity validation passed",
          "All active CIOCs within configured 85% max fill",
          "success",
        ],
        [
          "14:32:07.882",
          "Warning generated",
          "CAB-03/CIOC-02 spare margin below 15% target",
          "warning",
        ],
        [
          "14:32:07.301",
          "Rule profile applied",
          "STANDARD profile · 4 active rules · 1 inactive",
          "info",
        ],
        [
          "14:32:07.181",
          "Schedule validated",
          "200 rows · 7 fields · no duplicate signal tags",
          "success",
        ],
      ].map((a) => (
        <div className="audit-row" key={a[0]}>
          <time>{a[0]}</time>
          <span className={`audit-dot ${a[3]}`} />
          <div>
            <strong>{a[1]}</strong>
            <p>{a[2]}</p>
          </div>
        </div>
      ))}
    </div>
  )
}
