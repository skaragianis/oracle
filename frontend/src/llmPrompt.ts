import type { SearchResult } from './api'

const SYSTEM = `Answer using ONLY the provided sources. Cite every claim with
the source number in square brackets, e.g. [2]. Multiple sources: [1][3].
If the sources don't contain the answer, say so — do not use outside
knowledge. Never cite a number that isn't listed below.`

function citation(result: SearchResult): string {
  const page = result.page_number !== null ? `, p. ${result.page_number}` : ''
  return `${result.filename}${page}`
}

export function buildLlmPrompt(question: string, results: SearchResult[]): string {
  const sources = results
    .map((result, index) => `[${index + 1}] (${citation(result)})\n${result.text.trim()}`)
    .join('\n\n')
  return `System: ${SYSTEM}\n\nUser:\nSources:\n\n${sources}\n\nQuestion: ${question}`
}
