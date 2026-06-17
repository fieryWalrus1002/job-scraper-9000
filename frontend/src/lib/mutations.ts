/**
 * Standard onError handler for mutations: log the failure loudly. Without it a
 * failed mutation silently re-enables its button and leaves the UI stale, with
 * nothing in the console. Consuming components additionally surface
 * `mutation.error` inline so the user sees the failure.
 */
export function logMutationError(label: string) {
  return (error: unknown) => console.error(`Mutation failed: ${label}`, error)
}
