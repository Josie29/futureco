import { roster } from "@/api/fixtures"
import { computeEligibility } from "@/api/mock/catalogue"
import { buildPlan } from "@/api/mock/plans"
import { getTraceById, listTraces, recordPlanRun } from "@/api/mock/traces"
import { currentCoachId } from "@/features/auth/storage"
import type {
  Coach,
  CopilotMessage,
  Eligibility,
  MemberContext,
  MemberMessage,
  PlanRequest,
  RosterEntry,
  RunTrace,
  RunTraceSummary,
  WorkoutPlan,
} from "@/types"
import { ConstraintKind } from "@/types"

/**
 * The API surface, one function per documented endpoint.
 *
 * The read surface is live against the Python API; the generator and the
 * traces tab are still mock-backed and belong to a separate stream. Which is
 * which is marked below. No component knows where its data comes from, which
 * is what lets the two halves land at different times.
 *
 * | Method | Path                                        | Backed by |
 * |--------|---------------------------------------------|-----------|
 * | GET    | /api/coaches                                | API       |
 * | GET    | /api/members                                | API       |
 * | GET    | /api/members/{id}                           | API       |
 * | GET    | /api/members/{id}/messages                  | API       |
 * | GET    | /api/members/{id}/copilot                   | API       |
 * | GET    | /api/members/{id}/eligibility?disabled=…    | mock      |
 * | POST   | /api/members/{id}/plans                     | mock      |
 * | POST   | /api/members/{id}/plans/{run_id}/adjust     | mock      |
 * | POST   | /api/members/{id}/copilot                   | API       |
 * | GET    | /api/traces                                 | mock      |
 * | GET    | /api/traces/{run_id}                        | mock      |
 */

/** Rough shape of the latencies the still-mocked endpoints will show. */
const LATENCY = {
  read: 180,
  eligibility: 120,
  plan: 1400,
  copilot: 900,
} as const

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

function delay<T>(value: T, ms: number): Promise<T> {
  return new Promise((resolve) => window.setTimeout(() => resolve(value), ms))
}

/**
 * GET a JSON endpoint, sending the signed-in coach.
 *
 * `X-Coach-Id` comes from the session rather than from any argument, so no
 * call site can pass an identity it was handed. The API answers 404 unless a
 * `coaches` edge joins that coach to the member being read.
 *
 * @param path Absolute API path. Same-origin: the dev server proxies `/api`.
 * @returns The decoded body.
 * @throws ApiError When signed out, or when the API answers non-2xx. The
 *   server's `detail` is preferred over a generic message, because the API
 *   already writes those for a person to read.
 */
async function getJson<T>(path: string): Promise<T> {
  const coachId = currentCoachId()
  if (!coachId) throw new ApiError("Not signed in", 401)

  const response = await fetch(path, { headers: { "X-Coach-Id": coachId } })
  if (!response.ok) {
    const problem = await response
      .json()
      .catch(() => ({ detail: `The API returned ${response.status}.` }))
    throw new ApiError(problem.detail ?? `The API returned ${response.status}.`, response.status)
  }
  return response.json()
}

/** Injury items are never honoured, whatever the client sends. */
function dropInjuries(disabled: string[]): string[] {
  return disabled.filter((id) => !id.startsWith(`${ConstraintKind.INJURIES}:`))
}

/**
 * Guard for the endpoints still served by the generator mock.
 *
 * The live endpoints do this server-side against the graph. This stays only as
 * long as the mock does, and goes with it.
 *
 * @throws ApiError 404 for an unknown member, or one carrying no context.
 */
function requireMember(memberId: string): void {
  const entry = roster.find((m) => m.id === memberId)
  if (!entry) throw new ApiError(`No member ${memberId}`, 404)
  if (!entry.has_context) throw new ApiError(`No context loaded for ${entry.name}`, 404)
}

/** The sign-in list. The one call made before there is a coach to send. */
export async function getCoaches(): Promise<Coach[]> {
  const response = await fetch("/api/coaches")
  if (!response.ok) throw new ApiError("Couldn't load the coach list", response.status)
  return response.json()
}

export async function getRoster(): Promise<RosterEntry[]> {
  return getJson<RosterEntry[]>("/api/members")
}

/**
 * Full context for one member, assembled from KG2.
 *
 * @throws ApiError 404 when the member is not on this coach's roster, and when
 *   she is but the graph holds no context for her. The console renders a
 *   designed empty state for the second rather than fabricated clinical detail.
 */
export async function getMember(memberId: string): Promise<MemberContext> {
  return getJson<MemberContext>(`/api/members/${encodeURIComponent(memberId)}`)
}

/**
 * The standing eligible pool.
 *
 * `disabled` can never switch off an injury. The API loads injuries from the
 * member id and applies them unconditionally — there is no field the client
 * can send to turn them off, for the same reason the agent's tools don't
 * expose one.
 */
export async function getEligibility(
  memberId: string,
  disabled: string[],
): Promise<Eligibility> {
  requireMember(memberId)
  return delay(computeEligibility(dropInjuries(disabled)), LATENCY.eligibility)
}

export async function createPlan(memberId: string, request: PlanRequest): Promise<WorkoutPlan> {
  requireMember(memberId)
  if (!request.prompt.trim()) throw new ApiError("A prompt is required", 422)
  const plan = buildPlan({ ...request, disabled: dropInjuries(request.disabled) })
  recordPlanRun(plan)
  return delay(plan, LATENCY.plan)
}

/**
 * Adjust an existing plan.
 *
 * An adjustment is a new run with a parent pointer, never a mutation. The
 * trace of the run it came from stays intact and auditable.
 */
export async function adjustPlan(
  memberId: string,
  runId: string,
  request: PlanRequest,
): Promise<WorkoutPlan> {
  requireMember(memberId)
  if (!request.prompt.trim()) throw new ApiError("A prompt is required", 422)
  const plan = buildPlan({
    ...request,
    disabled: dropInjuries(request.disabled),
    parentRunId: runId,
  })
  recordPlanRun(plan)
  return delay(plan, LATENCY.plan)
}

export async function getMessages(memberId: string): Promise<MemberMessage[]> {
  return getJson<MemberMessage[]>(`/api/members/${encodeURIComponent(memberId)}/messages`)
}

/**
 * The thread, which arrives already answered.
 *
 * The morning brief is the first turn rather than a dashboard panel
 * (ASSESSMENT.md:71), so retrieval has run before the coach types anything.
 */
export async function getCopilotThread(memberId: string): Promise<CopilotMessage[]> {
  return getJson<CopilotMessage[]>(`/api/members/${encodeURIComponent(memberId)}/copilot`)
}

/**
 * Ask about the loaded member.
 *
 * `id` is ignored — the server assigns the turn's id, because it also records
 * the run under it. Kept in the signature so the caller's optimistic
 * placeholder still has something to key on while the answer is in flight.
 */
export async function askCopilot(
  memberId: string,
  prompt: string,
  _id: string,
): Promise<CopilotMessage> {
  const coachId = currentCoachId()
  if (!coachId) throw new ApiError("Not signed in", 401)

  const response = await fetch(`/api/members/${encodeURIComponent(memberId)}/copilot`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Coach-Id": coachId },
    body: JSON.stringify({ prompt }),
  })
  if (!response.ok) {
    const problem = await response
      .json()
      .catch(() => ({ detail: `The API returned ${response.status}.` }))
    throw new ApiError(problem.detail ?? "The copilot didn't answer.", response.status)
  }
  return response.json()
}

/**
 * Observability over the agentic runtime (ASSESSMENT.md:134).
 *
 * Separate endpoints from the plan itself: a trace outlives the response it
 * describes, and the console shouldn't have to hold one to show the other.
 */
export async function getTraces(): Promise<RunTraceSummary[]> {
  return delay(listTraces(), LATENCY.read)
}

/** @throws ApiError 404 when the run is unknown or has aged out. */
export async function getTrace(runId: string): Promise<RunTrace> {
  const trace = getTraceById(runId)
  if (!trace) throw new ApiError(`No trace for ${runId}`, 404)
  return delay(trace, LATENCY.read)
}
