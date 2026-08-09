import { coaches, member, memberMessages, roster } from "@/api/fixtures"
import { answer, openingBrief } from "@/api/mock/copilot"
import { getTraceById, listTraces, recordCopilotRun, recordPlanRun } from "@/api/mock/traces"
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
 * The generator is live: eligibility, plans and adjustments call the Python
 * backend, which builds them by traversing the knowledge graph. Everything
 * else is still mock-backed, because those endpoints do not exist yet — the
 * copilot in particular is unbuilt. The split is per function and no component
 * knows which side it is on.
 *
 * Vite proxies `/api` to the backend in development, and the container serves
 * both from one origin, so these paths are relative either way.
 *
 * | Method | Path                                        |
 * |--------|---------------------------------------------|
 * | GET    | /api/coaches                                |
 * | GET    | /api/members                                |
 * | GET    | /api/members/{id}                           |
 * | GET    | /api/members/{id}/eligibility?disabled=…    |
 * | POST   | /api/members/{id}/plans                     |
 * | POST   | /api/members/{id}/plans/{run_id}/adjust     |
 * | GET    | /api/members/{id}/messages                  |
 * | POST   | /api/members/{id}/copilot                   |
 * | GET    | /api/traces                                 |
 * | GET    | /api/traces/{run_id}                        |
 */

/** Rough shape of the latencies the mocked endpoints would show. */
const LATENCY = {
  read: 180,
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
 * Call the backend, turning a failure into the same `ApiError` the mocks throw.
 *
 * FastAPI puts its message in `detail`; anything else — a proxy error page, a
 * dead backend — has no JSON at all, so the status line is the only thing left
 * to report. Either way a caller sees one error type.
 *
 * @param path Absolute path beginning `/api`.
 * @param init Fetch options. Omit for a GET.
 * @returns The parsed JSON body.
 * @throws ApiError carrying the response status.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: init?.body ? { "content-type": "application/json" } : undefined,
    })
  } catch {
    throw new ApiError("Could not reach the API", 0)
  }
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined)
    throw new ApiError(detail ?? `Request failed (${response.status})`, response.status)
  }
  return response.json() as Promise<T>
}

/**
 * Every member-scoped endpoint checks the id, the way a real router would.
 *
 * @throws ApiError 404 for an unknown member, or one carrying no context.
 */
/** Injury items are never honoured, whatever the client sends. */
function dropInjuries(disabled: string[]): string[] {
  return disabled.filter((id) => !id.startsWith(`${ConstraintKind.INJURIES}:`))
}

function requireMember(memberId: string): void {
  const entry = roster.find((m) => m.id === memberId)
  if (!entry) throw new ApiError(`No member ${memberId}`, 404)
  if (!entry.has_context) throw new ApiError(`No context loaded for ${entry.name}`, 404)
}

export async function getCoaches(): Promise<Coach[]> {
  return delay(coaches, LATENCY.read)
}

export async function getRoster(): Promise<RosterEntry[]> {
  return delay(roster, LATENCY.read)
}

/**
 * Full context for one member.
 *
 * @throws ApiError 404 when the member carries no context. Only one member is
 *   populated in this dataset; the rest render a designed empty state rather
 *   than fabricated clinical detail.
 */
export async function getMember(memberId: string): Promise<MemberContext> {
  requireMember(memberId)
  return delay(member, LATENCY.read)
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
  const query = dropInjuries(disabled)
    .map((id) => `disabled=${encodeURIComponent(id)}`)
    .join("&")
  return request<Eligibility>(
    `/api/members/${encodeURIComponent(memberId)}/eligibility${query ? `?${query}` : ""}`,
  )
}

export async function createPlan(memberId: string, body: PlanRequest): Promise<WorkoutPlan> {
  if (!body.prompt.trim()) throw new ApiError("A prompt is required", 422)
  const plan = await request<WorkoutPlan>(
    `/api/members/${encodeURIComponent(memberId)}/plans`,
    { method: "POST", body: JSON.stringify({ ...body, disabled: dropInjuries(body.disabled) }) },
  )
  recordPlanRun(plan)
  return plan
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
  body: PlanRequest,
): Promise<WorkoutPlan> {
  if (!body.prompt.trim()) throw new ApiError("A prompt is required", 422)
  const plan = await request<WorkoutPlan>(
    `/api/members/${encodeURIComponent(memberId)}/plans/${encodeURIComponent(runId)}/adjust`,
    { method: "POST", body: JSON.stringify({ ...body, disabled: dropInjuries(body.disabled) }) },
  )
  recordPlanRun(plan)
  return plan
}

export async function getMessages(memberId: string): Promise<MemberMessage[]> {
  requireMember(memberId)
  return delay(memberMessages, LATENCY.read)
}

export async function getCopilotThread(memberId: string): Promise<CopilotMessage[]> {
  requireMember(memberId)
  return delay([openingBrief], LATENCY.read)
}

export async function askCopilot(
  memberId: string,
  prompt: string,
  id: string,
): Promise<CopilotMessage> {
  requireMember(memberId)
  recordCopilotRun(`run_${id}`, prompt)
  return delay(answer(prompt, id), LATENCY.copilot)
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
