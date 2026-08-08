import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"
import type { Coach, Session } from "@/types"

/**
 * Mock coach auth. "Mock auth is fine" (ASSESSMENT.md:72), so this is
 * deliberately trivial: a coach is picked, the choice is kept in
 * `localStorage`, and unauthenticated routes redirect.
 *
 * It earns its place by proving the boundary exists. The member id in a URL
 * is not authority to read that member — the API loads the coach from the
 * session, which is also why `disabled[]` can never switch an injury off.
 */

const STORAGE_KEY = "future.coach-session"

function read(): Session | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Session>
    // A shape check, because a stale key from an older build would otherwise
    // crash the header rather than sending the coach back to sign in.
    if (!parsed?.coach?.id || !parsed.coach.name) return null
    return { coach: parsed.coach as Coach, signed_in_at: parsed.signed_in_at ?? "" }
  } catch {
    return null
  }
}

interface SessionValue {
  session: Session | null
  signIn: (coach: Coach) => void
  signOut: () => void
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(read)

  const signIn = useCallback((coach: Coach) => {
    const next: Session = { coach, signed_in_at: new Date().toISOString() }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    setSession(next)
  }, [])

  const signOut = useCallback(() => {
    window.localStorage.removeItem(STORAGE_KEY)
    setSession(null)
  }, [])

  const value = useMemo(() => ({ session, signIn, signOut }), [session, signIn, signOut])
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

/**
 * The current session.
 *
 * @throws Error when called outside a SessionProvider, which is a wiring bug
 *   rather than a runtime condition.
 */
export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error("useSession must be used inside a SessionProvider")
  return value
}
