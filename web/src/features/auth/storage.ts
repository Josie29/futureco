import type { Coach, Session } from "@/types"

/**
 * Where the mock coach session lives, and how to read it.
 *
 * Split out of `session.tsx` so the API layer can send the coach id without
 * importing a React context it has no business rendering. Both sides read the
 * same key, so there is one definition of "who is signed in".
 */

const STORAGE_KEY = "future.coach-session"

/**
 * Read the stored session.
 *
 * @returns The session, or null when absent or written by an older build. A
 *   stale key is treated as signed-out rather than crashing the header.
 */
export function readSession(): Session | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Session>
    if (!parsed?.coach?.id || !parsed.coach.name) return null
    return { coach: parsed.coach as Coach, signed_in_at: parsed.signed_in_at ?? "" }
  } catch {
    return null
  }
}

/** Persist a signed-in coach. */
export function writeSession(session: Session): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

/** Forget the signed-in coach. */
export function clearSession(): void {
  window.localStorage.removeItem(STORAGE_KEY)
}

/**
 * The signed-in coach's id, for the `X-Coach-Id` header.
 *
 * @returns The id, or null when signed out — in which case the call should not
 *   be made rather than being made anonymously.
 */
export function currentCoachId(): string | null {
  return readSession()?.coach.id ?? null
}
