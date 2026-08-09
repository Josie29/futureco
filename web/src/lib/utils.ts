import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * Merge conditional class names, with later Tailwind utilities winning
 * conflicts rather than both landing in the class list.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/**
 * Format a duration in minutes for display.
 *
 * The API already rounds each figure to one decimal, but the console does
 * arithmetic on them — summing a block's exercises, subtracting the estimate
 * from the requested window — and binary floating point turns that into
 * `2.9000000000000004 min` and `0.7000000000000028 spare`. Rounding at the
 * point of display fixes every such site at once, and is the right place for
 * it: the error is introduced by the arithmetic, not by the data.
 *
 * A whole number renders without a decimal point, so a 45-minute session reads
 * `45` rather than `45.0`.
 *
 * @param value Minutes, possibly carrying floating-point noise.
 * @returns The number to one decimal place, with a trailing `.0` dropped.
 */
export function formatMinutes(value: number): string {
  return String(Number(value.toFixed(1)))
}
