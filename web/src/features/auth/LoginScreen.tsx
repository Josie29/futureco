import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useLocation, useNavigate } from "react-router-dom"
import { getCoaches } from "@/api/client"
import { useSession } from "@/features/auth/session"

/**
 * Coach sign-in. Any credentials work — the point is the boundary, not the
 * check. Which coach you are decides which roster you see, so the choice is
 * the only field that does anything.
 */
export function LoginScreen() {
  const { signIn } = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const { data: coaches, isPending, isError } = useQuery({ queryKey: ["coaches"], queryFn: getCoaches })
  const [coachId, setCoachId] = useState<string | null>(null)

  const selected = coaches?.find((c) => c.id === coachId) ?? coaches?.[0] ?? null

  // `RequireSession` records where the coach was headed. Sending them to the
  // roster instead would make every deep link into a signed-out browser lose
  // its destination — the link works, and then quietly doesn't.
  const destination = (location.state as { from?: string } | null)?.from
  const returnTo = destination && destination !== "/login" ? destination : "/"

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!selected) return
    signIn(selected)
    navigate(returnTo, { replace: true })
  }

  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <form onSubmit={submit} className="w-full max-w-xs">
        <p className="disp text-2xl leading-tight">future</p>
        <p className="mt-1 text-meta text-dim">
          Coach console. Sign-in is mocked — pick who you are and go.
        </p>

        <label htmlFor="coach" className="mt-5 mb-1.5 block text-meta font-semibold text-dim">
          Signing in as
        </label>

        {isError ? (
          <p className="rounded-[4px] border border-red bg-red-wash p-2 text-meta text-red">
            Couldn't reach the coach directory. Reload to try again.
          </p>
        ) : (
          <select
            id="coach"
            value={selected?.id ?? ""}
            disabled={isPending || !coaches?.length}
            onChange={(e) => setCoachId(e.target.value)}
            className="w-full rounded-[4px] border-[1.5px] border-ink bg-card px-2.5 py-2 text-sm"
          >
            {isPending && <option>Loading…</option>}
            {coaches?.map((coach) => (
              <option key={coach.id} value={coach.id}>
                {coach.name}
              </option>
            ))}
          </select>
        )}

        <button
          type="submit"
          disabled={!selected}
          className="mt-3 w-full rounded-[4px] bg-ink px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
        >
          Open the console
        </button>
      </form>
    </div>
  )
}
