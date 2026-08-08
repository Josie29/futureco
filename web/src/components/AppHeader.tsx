import { NavLink } from "react-router-dom"
import { useSession } from "@/features/auth/session"
import { cn } from "@/lib/utils"

const TABS = [
  { to: "/", label: "Console" },
  { to: "/admin/graph", label: "Graph" },
  { to: "/traces", label: "Traces" },
] as const

/**
 * The header reads the coach off the session rather than fetching one, so who
 * you are and what you are allowed to see come from the same place.
 */
export function AppHeader() {
  const { session, signOut } = useSession()

  return (
    <header className="flex items-center gap-4 border-b border-line bg-card px-3.5 py-2">
      <span className="text-body font-semibold">
        future <span className="font-normal text-faint">· coach console</span>
      </span>

      <nav className="flex gap-0.5">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === "/"}
            className={({ isActive }) =>
              cn(
                "rounded-[4px] px-2 py-0.5 text-micro font-semibold",
                isActive ? "bg-ground text-ink" : "text-faint hover:text-dim",
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <span className="ml-auto flex items-center gap-2.5">
        <span className="text-micro text-dim">{session?.coach.name}</span>
        <button
          type="button"
          onClick={signOut}
          className="text-micro text-faint underline underline-offset-2 hover:text-ink"
        >
          Sign out
        </button>
      </span>
    </header>
  )
}
