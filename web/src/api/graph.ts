import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import type { ApiProblem, GraphScope, InstanceGraph, SchemaGraph } from "@/types/graph"

/** An API response that arrived and said no, as opposed to a network failure. */
export class ApiError extends Error {
  readonly status: number
  readonly remedy: string | null

  constructor(status: number, problem: ApiProblem) {
    super(problem.detail)
    this.name = "ApiError"
    this.status = status
    this.remedy = problem.remedy ?? null
  }
}

/**
 * Fetch the meta-graph for one scope.
 *
 * @param scope Which subgraph to describe.
 * @param signal Abort signal from the query client.
 * @returns The node types, edge types and totals, counted from the store.
 * @throws {ApiError} When the API answers with a non-2xx status, carrying the
 *   remedy text so the UI can show the command that fixes it.
 */
async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })

  if (!response.ok) {
    // A proxy or crash can return HTML where the contract promises JSON, so a
    // parse failure must not mask the status code that actually explains it.
    const problem: ApiProblem = await response
      .json()
      .catch(() => ({ detail: `The graph API returned ${response.status}.` }))
    throw new ApiError(response.status, problem)
  }

  return response.json()
}

export function useSchemaGraph(scope: GraphScope): UseQueryResult<SchemaGraph, Error> {
  return useQuery({
    queryKey: ["graph", "schema", scope],
    queryFn: ({ signal }) => getJson<SchemaGraph>(`/api/graph/schema?scope=${scope}`, signal),
    // The graph only changes when someone re-runs the build, so refetching on
    // every window focus would be noise.
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: (failureCount, error) =>
      // A database that is down stays down until someone starts it; retrying
      // just delays the message that says so.
      !(error instanceof ApiError && error.status === 503) && failureCount < 2,
  })
}

/**
 * The instance graph, as a whole or centred on one node.
 *
 * @param scope Which subgraph to keep.
 * @param full When true, load every node instead of a neighbourhood.
 * @param rootId Centre the view on this node. Takes precedence over `full`,
 *   because a request to focus somewhere is more specific than a request to
 *   see everything.
 */
export function useInstanceGraph(
  scope: GraphScope,
  full: boolean,
  rootId: string | null,
): UseQueryResult<InstanceGraph, Error> {
  return useQuery({
    queryKey: ["graph", "instances", scope, full, rootId],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ scope })
      if (rootId) {
        params.set("root", rootId)
        params.set("depth", "1")
      } else {
        params.set("full", String(full))
      }
      return getJson<InstanceGraph>(`/api/graph/instances?${params}`, signal)
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 503) && failureCount < 2,
  })
}

/**
 * Fetch one node's neighbours, for expanding the graph in place.
 *
 * Called imperatively on click rather than through a hook, because the result
 * is merged into a running Cytoscape instance rather than re-rendered.
 *
 * @param nodeId `elementId` of the node to expand.
 * @param scope Which subgraph to keep.
 * @returns The subgraph within one hop.
 * @throws {ApiError} When the API answers with a non-2xx status.
 */
export function fetchNeighbourhood(nodeId: string, scope: GraphScope): Promise<InstanceGraph> {
  const id = encodeURIComponent(nodeId)
  return getJson<InstanceGraph>(`/api/graph/instances?scope=${scope}&root=${id}&depth=1`)
}
