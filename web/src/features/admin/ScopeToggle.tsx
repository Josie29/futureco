import { cn } from "@/lib/utils"
import { GraphScope } from "@/types/graph"

/** Each scope answers a different question, so the hint is the question. */
export const SCOPES: { scope: GraphScope; label: string; hint: string }[] = [
  { scope: GraphScope.KG1, label: "KG1", hint: "What the system knows" },
  { scope: GraphScope.KG2, label: "KG2", hint: "Who we are planning for" },
  { scope: GraphScope.BOTH, label: "Both", hint: "Where the two graphs meet" },
]

export function scopeHint(scope: GraphScope): string {
  return SCOPES.find((s) => s.scope === scope)?.hint ?? ""
}

export function ScopeToggle({
  scope,
  onChange,
}: {
  scope: GraphScope
  onChange: (scope: GraphScope) => void
}) {
  return (
    <div className="inline-flex rounded-[4px] border border-line bg-card p-0.5" role="tablist">
      {SCOPES.map((option) => {
        const active = option.scope === scope
        return (
          <button
            key={option.scope}
            type="button"
            role="tab"
            aria-selected={active}
            title={option.hint}
            onClick={() => onChange(option.scope)}
            className={cn(
              "rounded-[3px] px-2.5 py-1 text-xs font-semibold",
              active ? "bg-ink text-white" : "text-dim hover:text-ink",
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
