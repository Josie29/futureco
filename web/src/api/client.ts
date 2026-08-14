import { currentCoachId } from "@/features/auth/storage"
import type {
  Coach,
  CopilotMessage,
  Eligibility,
  MemberContext,
  MemberMessage,
  PlanRequest,
  PlanResponse,
  RosterEntry,
  RunTrace,
  RunTraceSummary,
} from "@/types"

/**
 * The API surface, one function per documented endpoint.
 *
 * Every function here calls the Python backend. Nothing in the console is
 * mock-backed any more: the generator traverses the graph, the member panels
 * and copilot read KG2, and the traces tab reads runs both surfaces actually
 * recorded.
 *
 * Vite proxies `/api` to the backend in development, and the container serves
 * both from one origin, so these paths are relative either way.
 *
 * | Method | Path                                     |
 * |--------|------------------------------------------|
 * | GET    | /api/coaches                             |
 * | GET    | /api/members                             |
 * | GET    | /api/members/{id}                        |
 * | GET    | /api/members/{id}/messages               |
 * | GET    | /api/members/{id}/eligibility?disabled=… |
 * | POST   | /api/members/{id}/plans                  |
 * | POST   | /api/members/{id}/plans/{run_id}/adjust  |
 * | GET    | /api/members/{id}/copilot                |
 * | POST   | /api/members/{id}/copilot                |
 * | GET    | /api/traces                              |
 * | GET    | /api/traces/{run_id}                     |
 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

/**
 * Call the backend as the signed-in coach.
 *
 * `X-Coach-Id` comes from stored session rather than from any argument, so no
 * call site can pass an identity it was handed. The API answers 404 unless a
 * `coaches` edge joins that coach to the member being read — which is what
 * makes the console's mock login an actual boundary.
 *
 * FastAPI puts its message in `detail`; anything else — a proxy error page, a
 * dead backend — has no JSON at all, so the status line is the only thing left
 * to report. Either way a caller sees one error type.
 *
 * @param path Absolute path beginning `/api`.
 * @param init Fetch options. Omit for a GET.
 * @param anonymous Send no coach header. Only `/api/coaches` sets this — it is
 *   the screen reached before there is a coach to send.
 * @returns The parsed JSON body.
 * @throws ApiError carrying the response status, or 0 when the API was
 *   unreachable and 401 when nobody is signed in.
 */
async function request<T>(
  path: string,
  init?: RequestInit,
  anonymous = false,
): Promise<T> {
  const headers: Record<string, string> = {}
  if (init?.body) headers["content-type"] = "application/json"
  if (!anonymous) {
    const coachId = currentCoachId()
    if (!coachId) throw new ApiError("Not signed in", 401)
    headers["X-Coach-Id"] = coachId
  }

  let response: Response
  try {
    response = await fetch(path, { ...init, headers })
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

/** The sign-in list. The one call made before there is a coach to send. */
export async function getCoaches(): Promise<Coach[]> {
  return request<Coach[]>("/api/coaches", undefined, true)
}

export async function getRoster(): Promise<RosterEntry[]> {
  return request<RosterEntry[]>("/api/members")
}

/**
 * Full context for one member, assembled from KG2.
 *
 * @throws ApiError 404 when the member is not on this coach's roster, and when
 *   she is but the graph holds no context for her. The console renders a
 *   designed empty state for the second rather than fabricated clinical detail.
 */
export async function getMember(memberId: string): Promise<MemberContext> {
  return request<MemberContext>(`/api/members/${encodeURIComponent(memberId)}`)
}

/** How the catalog stands for this member: clinical blocks, cautions, dislikes. */
export async function getEligibility(memberId: string): Promise<Eligibility> {
  return request<Eligibility>(`/api/members/${encodeURIComponent(memberId)}/eligibility`)
}

export async function createPlan(memberId: string, body: PlanRequest): Promise<PlanResponse> {
  if (!body.prompt.trim()) throw new ApiError("A prompt is required", 422)
  return request<PlanResponse>(`/api/members/${encodeURIComponent(memberId)}/plans`, {
    method: "POST",
    body: JSON.stringify(body),
  })
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
): Promise<PlanResponse> {
  if (!body.prompt.trim()) throw new ApiError("A prompt is required", 422)
  return request<PlanResponse>(
    `/api/members/${encodeURIComponent(memberId)}/plans/${encodeURIComponent(runId)}/adjust`,
    { method: "POST", body: JSON.stringify(body) },
  )
}

export async function getMessages(memberId: string): Promise<MemberMessage[]> {
  return request<MemberMessage[]>(`/api/members/${encodeURIComponent(memberId)}/messages`)
}

/**
 * The thread, which arrives already answered.
 *
 * The morning brief is the first turn rather than a dashboard panel
 * (ASSESSMENT.md:71), so retrieval has run before the coach types anything.
 */
export async function getCopilotThread(memberId: string): Promise<CopilotMessage[]> {
  return request<CopilotMessage[]>(`/api/members/${encodeURIComponent(memberId)}/copilot`)
}

/**
 * Ask about the loaded member.
 *
 * The `id` argument is ignored — the server assigns the turn's id, because it
 * records the run under it. Kept in the signature so a caller's optimistic
 * placeholder still has something to key on while the answer is in flight.
 */
export async function askCopilot(
  memberId: string,
  prompt: string,
  _id: string,
): Promise<CopilotMessage> {
  return request<CopilotMessage>(`/api/members/${encodeURIComponent(memberId)}/copilot`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  })
}

/** Every run the backend recorded, generator and copilot, newest first. */
export async function getTraces(): Promise<RunTraceSummary[]> {
  return request<RunTraceSummary[]>("/api/traces")
}

/**
 * One run's span waterfall.
 *
 * @throws ApiError 404 when the run is unknown, or has aged out of the
 *   in-memory ring on a backend running without Postgres.
 */
export async function getTrace(runId: string): Promise<RunTrace> {
  return request<RunTrace>(`/api/traces/${encodeURIComponent(runId)}`)
}
