import { createContext, useContext } from 'react'

/** Keys that exist in a published version (locked: renaming would split their data). */
export const PublishedContext = createContext<ReadonlySet<string>>(new Set())

export function usePublished(): ReadonlySet<string> {
  return useContext(PublishedContext)
}
