/**
 * Visibility dependency graph and cycle detection. Twin of backend/app/logic/graph.py;
 * see that file for the edge rules.
 */
import { type FormIndex, iterLeaves, pageNode, visibleIfOf } from './form-index'

export function buildGraph(index: FormIndex): Map<string, string[]> {
  const graph = new Map<string, string[]>()

  for (const info of index.elements.values()) {
    const deps: string[] = [info.parentId ?? pageNode(index.pages[info.pageIndex].id)]
    for (const leaf of iterLeaves(visibleIfOf(info.element))) deps.push(leaf.field)
    graph.set(info.id, deps)
  }

  let readsBefore: string[] = []
  for (const page of index.pages) {
    const own = [...iterLeaves(page.visibleIf)].map((l) => l.field)
    graph.set(pageNode(page.id), [...readsBefore, ...own])
    const nav = (page.next ?? []).flatMap((rule) => [...iterLeaves(rule.if)].map((l) => l.field))
    readsBefore = [...readsBefore, ...own, ...nav]
  }
  return graph
}

/** One cycle as `[a, b, ..., a]`, or null. Unknown nodes are ignored. */
export function findCycle(graph: Map<string, string[]>): string[] | null {
  const WHITE = 0
  const GREY = 1
  const BLACK = 2
  const color = new Map<string, number>()
  for (const node of graph.keys()) color.set(node, WHITE)

  for (const start of graph.keys()) {
    if (color.get(start) !== WHITE) continue
    const stack: [string, number][] = [[start, 0]]
    const path = [start]
    color.set(start, GREY)
    while (stack.length) {
      const top = stack[stack.length - 1]
      const [node, i] = top
      const deps = graph.get(node)!
      if (i < deps.length) {
        top[1] = i + 1
        const next = deps[i]
        const c = color.get(next)
        if (c === undefined) continue
        if (c === GREY) return [...path.slice(path.indexOf(next)), next]
        if (c === WHITE) {
          color.set(next, GREY)
          stack.push([next, 0])
          path.push(next)
        }
      } else {
        color.set(node, BLACK)
        stack.pop()
        path.pop()
      }
    }
  }
  return null
}
