"use client"

import {
  useEffect,
  useId,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react"
import { motion, useReducedMotion, useSpring, useTransform } from "motion/react"
import { cn } from "../lib/utils"

const SPRING = { type: "spring", stiffness: 200, damping: 28, mass: 1 } as const
const NECK_BREAK = 0.22
const NECK_H = 100
const SIZES = {
  xs: { label: "gooey-label-xs", radius: 7, separation: 11 },
  sm: { label: "gooey-label-sm", radius: 8, separation: 13 },
  md: { label: "gooey-label-md", radius: 10, separation: 16 },
  lg: { label: "gooey-label-lg", radius: 12, separation: 20 },
} as const

export type GooeyNavSize = keyof typeof SIZES
type NavItem = { label: string icon?: ReactNode }
export type GooeyNavItem = string | NavItem
const toItem = (item: GooeyNavItem): NavItem =>
  typeof item === "string" ? { label: item } : item

function neckPath(gap: number, span: number) {
  if (!Number.isFinite(gap) || !Number.isFinite(span) || gap <= 0 || span <= 0)
    return ""
  const waist = NECK_H * (1 - gap / (span * NECK_BREAK))
  if (waist <= 0) return ""
  const start = span - gap
  const mid = start + gap / 2
  return `M${start} 0 Q${mid} ${NECK_H - waist} ${span} 0 L${span} ${NECK_H} Q${mid} ${waist} ${start} ${NECK_H} Z`
}

type SegmentProps = {
  gap: number
  span: number
  hasSeam: boolean
  leftFill: string
  rightFill: string
  reduced: boolean
  radii: Record<string, number>
  className?: string
  style?: CSSProperties
  children: ReactNode
}

function Segment({
  gap,
  span,
  hasSeam,
  leftFill,
  rightFill,
  reduced,
  radii,
  className,
  style,
  children,
}: SegmentProps) {
  const marginLeft = useSpring(gap, SPRING)
  const gradientId = `gooey-neck-${useId().replace(/:/g, "")}`
  useEffect(() => {
    if (reduced) marginLeft.jump(gap)
    else marginLeft.set(gap)
  }, [gap, marginLeft, reduced])
  const d = useTransform(marginLeft, (g) => neckPath(g, span))
  return (
    <motion.li
      className={cn("gooey-segment", className)}
      style={{ ...style, marginLeft }}
      initial={false}
      animate={radii}
      transition={reduced ? { duration: 0 } : SPRING}
    >
      {hasSeam && (
        <svg
          aria-hidden
          width={span}
          viewBox={`0 0 ${span} ${NECK_H}`}
          preserveAspectRatio="none"
          className="gooey-neck"
        >
          <defs>
            <linearGradient id={gradientId} x1="0" x2="1">
              <stop offset="0" stopColor={leftFill} />
              <stop offset="1" stopColor={rightFill} />
            </linearGradient>
          </defs>
          <motion.path d={d} fill={`url(#${gradientId})`} />
        </svg>
      )}
      {children}
    </motion.li>
  )
}

export type GooeyNavProps = {
  items: GooeyNavItem[]
  value?: number
  defaultValue?: number
  onChange?: (index: number) => void
  size?: GooeyNavSize
  activeColor?: string
  activeLabelColor?: string
  separation?: number
  radius?: number
  className?: string
}

export function GooeyNav({
  items,
  value,
  defaultValue = 0,
  onChange,
  size = "sm",
  activeColor = "#1d4ed8",
  activeLabelColor = "#eff6ff",
  separation,
  radius,
  className,
}: GooeyNavProps) {
  const reduced = useReducedMotion() ?? false
  const [uncontrolled, setUncontrolled] = useState(defaultValue)
  const active = value ?? uncontrolled
  const span = separation ?? SIZES[size].separation
  const corner = radius ?? SIZES[size].radius
  const open = (seam: number) =>
    seam === 0 ||
    seam === items.length ||
    seam - 1 === active ||
    seam === active
  const fill = (i: number) => (i === active ? activeColor : "#0b121f")

  return (
    <nav className={cn("gooey-nav", className)} aria-label="Main navigation">
      <ul>
        {items.map((item, i) => {
          const navItem = toItem(item)
          const isActive = i === active
          return (
            <Segment
              key={`${i}-${navItem.label}`}
              gap={i === 0 ? 0 : open(i) ? span : -1}
              span={span}
              hasSeam={i > 0}
              leftFill={fill(i - 1)}
              rightFill={fill(i)}
              reduced={reduced}
              radii={{
                borderTopLeftRadius: open(i) ? corner : 0,
                borderBottomLeftRadius: open(i) ? corner : 0,
                borderTopRightRadius: open(i + 1) ? corner : 0,
                borderBottomRightRadius: open(i + 1) ? corner : 0,
              }}
              className={isActive ? "active" : ""}
              style={{ backgroundColor: fill(i) }}
            >
              <button
                type="button"
                aria-current={isActive ? "page" : undefined}
                className={cn("gooey-label", SIZES[size].label)}
                style={isActive ? { color: activeLabelColor } : undefined}
                onClick={() => {
                  if (value === undefined) setUncontrolled(i)
                  onChange?.(i)
                }}
              >
                {navItem.icon}
                {navItem.label}
              </button>
            </Segment>
          )
        })}
      </ul>
    </nav>
  )
}
