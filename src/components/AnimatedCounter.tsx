"use client"

import { memo, useEffect, useMemo, useRef, useState } from "react"
import type { ComponentProps, ReactNode, Ref } from "react"
import {
  animate,
  AnimatePresence,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type Transition,
} from "motion/react"

import { cn } from "../lib/utils"

const FACES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
const WHEEL = [...FACES, 0]
const LINE = 1.5
const FADE = `linear-gradient(to bottom,
  rgba(0,0,0,0) 0%, rgba(0,0,0,0.06) 5.5%, rgba(0,0,0,0.5) 11%,
  rgba(0,0,0,0.94) 16.5%, #000 22%, #000 78%, rgba(0,0,0,0.94) 83.5%,
  rgba(0,0,0,0.5) 89%, rgba(0,0,0,0.06) 94.5%, rgba(0,0,0,0) 100%)`
const EASE = [0.22, 1, 0.36, 1] as const
const LEAVE = { duration: 0.18, ease: EASE } as const
const INSTANT = { duration: 0 } as const
const spring = (duration: number): Transition => ({
  type: "spring",
  visualDuration: duration,
  bounce: 0.18,
})
const mod = (n: number, m: number) => ((n % m) + m) % m
const clamp = (n: number, low: number, high: number) =>
  Math.min(high, Math.max(low, Number.isFinite(n) ? n : low))
const isDigit = (char: string) => char >= "0" && char <= "9"

const SIZER = FACES.map((face) => (
  <span key={face} aria-hidden className="invisible [grid-area:1/1]">
    {face}
  </span>
))
const STACK = WHEEL.map((face, index) => (
  <span
    key={index}
    className="flex items-center justify-center"
    style={{ height: `${LINE}em` }}
  >
    {face}
  </span>
))

export type Grouping = "western" | "indian"
const EVERY_THREE = /\B(?=(\d{3})+(?!\d))/g
const EVERY_TWO = /\B(?=(\d{2})+(?!\d))/g

function group(whole: string, separator: string, grouping: Grouping) {
  if (!separator) return whole
  if (grouping !== "indian") return whole.replace(EVERY_THREE, separator)
  const head = whole.slice(0, -3)
  return head
    ? `${head.replace(EVERY_TWO, separator)}${separator}${whole.slice(-3)}`
    : whole
}

type Shape = {
  amount: number
  scaled: number
  places: number
  pace: number
  width: number
}

function measure(
  value: number,
  decimals: number,
  padStart: number,
  duration: number,
): Shape {
  const amount = Number.isFinite(value) ? value : 0
  const places = clamp(Math.trunc(decimals), 0, 15)
  const pad = clamp(Math.trunc(padStart), 1, 24)
  const scaled = Math.min(
    Number.MAX_SAFE_INTEGER,
    Math.round(Math.abs(amount) * 10 ** places),
  )
  return {
    amount,
    scaled,
    places,
    pace: clamp(duration, 0.01, 60),
    width: Math.max(String(scaled).length, places + pad),
  }
}

function format(
  shape: Shape,
  separator: string,
  decimalSeparator: string,
  grouping: Grouping,
) {
  const raw = String(shape.scaled).padStart(shape.width, "0")
  const whole = group(
    raw.slice(0, raw.length - shape.places) || "0",
    separator,
    grouping,
  )
  return shape.places
    ? `${whole}${decimalSeparator}${raw.slice(raw.length - shape.places)}`
    : whole
}

type Cell = { kind: "digit" key: number digit: number } | {
  kind: "mark"
  key: string
  char: string
}

function toCells(chars: string, width: number): Cell[] {
  const cells: Cell[] = []
  let seen = 0
  let run = 0
  for (const char of chars) {
    if (isDigit(char)) {
      run = 0
      cells.push({ kind: "digit", key: width - seen++, digit: Number(char) })
    } else {
      cells.push({ kind: "mark", key: `mark-${width - seen}-${run++}`, char })
    }
  }
  return cells
}

function useWheel(
  from: number,
  digit: number,
  dir: number,
  duration: number,
  reduced: boolean,
) {
  const pos = useMotionValue(from)
  const goal = useRef(from)
  const heading = useRef(dir)
  useEffect(() => {
    heading.current = dir
  }, [dir])
  useEffect(() => {
    if (reduced) {
      goal.current = digit
      pos.set(digit)
      return
    }
    if (mod(goal.current, 10) !== digit) {
      const at = pos.get()
      goal.current =
        heading.current < 0
          ? at - mod(at - digit, 10)
          : at + mod(digit - at, 10)
    }
    const roll = animate(pos, goal.current, spring(duration))
    return () => roll.stop()
  }, [digit, duration, reduced, pos])
  return useTransform(pos, (p) => `${(-mod(p, 10) * 100) / WHEEL.length}%`)
}

type SlotProps = { reduced: boolean dep: number shift: Transition }
const shifts = ({ reduced, dep, shift }: SlotProps) => ({
  layout: !reduced,
  layoutDependency: dep,
  transition: shift,
})
const fades = (reduced: boolean) => ({
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0, transition: reduced ? INSTANT : LEAVE },
})

function Fixed({ children, ...slot }: SlotProps & { children: ReactNode }) {
  return (
    <motion.span {...shifts(slot)} className="inline-block">
      {children}
    </motion.span>
  )
}

function Mark({
  char,
  ref,
  ...slot
}: SlotProps & { char: string ref?: Ref<HTMLSpanElement> }) {
  return (
    <motion.span
      ref={ref}
      {...shifts(slot)}
      {...fades(slot.reduced)}
      className="inline-block"
    >
      {char}
    </motion.span>
  )
}

const Digit = memo(function Digit({
  digit,
  from,
  dir,
  duration,
  ref,
  ...slot
}: SlotProps & {
  digit: number
  from: number
  dir: number
  duration: number
  ref?: Ref<HTMLSpanElement>
}) {
  const y = useWheel(from, digit, dir, duration, slot.reduced)
  return (
    <motion.span
      ref={ref}
      {...shifts(slot)}
      {...fades(slot.reduced)}
      className="relative inline-grid overflow-hidden"
      style={{
        height: `${LINE}em`,
        lineHeight: LINE,
        maskImage: FADE,
        WebkitMaskImage: FADE,
      }}
    >
      {SIZER}
      <motion.span style={{ y }} className="absolute inset-x-0 top-0">
        {STACK}
      </motion.span>
    </motion.span>
  )
})

export type AnimatedCounterProps = Omit<ComponentProps<"span">, "children" | "prefix" | "onAnimationStart" | "onDrag" | "onDragStart" | "onDragEnd"> & {
  value: number
  decimals?: number
  duration?: number
  padStart?: number
  separator?: string
  decimalSeparator?: string
  grouping?: Grouping
  prefix?: ReactNode
  suffix?: ReactNode
}

export function AnimatedCounter({
  value,
  decimals = 0,
  duration = 0.6,
  padStart = 1,
  separator = ",",
  decimalSeparator = ".",
  grouping = "western",
  prefix,
  suffix,
  className,
  ...props
}: AnimatedCounterProps) {
  const reduced = useReducedMotion() ?? false
  const shape = measure(value, decimals, padStart, duration)
  const chars = format(shape, separator, decimalSeparator, grouping)
  const cells = toCells(chars, shape.width)
  const negative = shape.amount < 0 && shape.scaled > 0
  const [previous, setPrevious] = useState(shape.amount)
  const [dir, setDir] = useState(1)
  if (previous !== shape.amount) {
    setDir(shape.amount >= previous ? 1 : -1)
    setPrevious(shape.amount)
  }
  const [seed] = useState(() => {
    const faces: Record<number, number> = {}
    for (const cell of cells)
      if (cell.kind === "digit") faces[cell.key] = cell.digit
    return faces
  })
  const shift = useMemo<Transition>(
    () => (reduced ? INSTANT : spring(shape.pace)),
    [reduced, shape.pace],
  )
  const slot: SlotProps = { reduced, dep: chars.length, shift }

  return (
    <span
      className={cn("inline-flex items-center tabular-nums", className)}
      {...props}
    >
      {prefix != null && <Fixed {...slot}>{prefix}</Fixed>}
      <span className="sr-only">
        {negative ? "-" : ""}
        {chars}
      </span>
      <span aria-hidden className="inline-flex select-none items-center">
        {negative && <Fixed {...slot}>-</Fixed>}
        <AnimatePresence mode="popLayout" initial={false}>
          {cells.map((cell) =>
            cell.kind === "digit" ? (
              <Digit
                key={cell.key}
                {...slot}
                digit={cell.digit}
                from={seed[cell.key] ?? 0}
                dir={dir}
                duration={shape.pace}
              />
            ) : (
              <Mark key={cell.key} {...slot} char={cell.char} />
            ),
          )}
        </AnimatePresence>
      </span>
      {suffix != null && <Fixed {...slot}>{suffix}</Fixed>}
    </span>
  )
}

export default AnimatedCounter
