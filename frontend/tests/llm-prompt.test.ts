import { describe, expect, it } from 'vitest'

import { buildLlmPrompt } from '../src/llmPrompt'
import type { SearchResult } from '../src/api'

const RESULTS: SearchResult[] = [
  {
    doc_id: 1,
    filename: 'first.pdf',
    chunk_id: 10,
    seq: 0,
    text: 'the quick brown fox',
    page_number: 4,
    sources: ['bm25', 'vector'],
  },
  {
    doc_id: 2,
    filename: 'second.pdf',
    chunk_id: 20,
    seq: 1,
    text: 'a slow brown bear',
    page_number: null,
    sources: ['vector'],
  },
]

describe('buildLlmPrompt', () => {
  it('numbers sources and cites filename and page', () => {
    const prompt = buildLlmPrompt('brown animals', RESULTS)

    expect(prompt).toContain('[1] (first.pdf, p. 4)')
    expect(prompt).toContain('the quick brown fox')
  })

  it('omits the page when a result has none', () => {
    const prompt = buildLlmPrompt('brown animals', RESULTS)

    expect(prompt).toContain('[2] (second.pdf)')
    expect(prompt).not.toContain('second.pdf, p.')
  })

  it('includes the system instructions, question, and scaffolding', () => {
    const prompt = buildLlmPrompt('brown animals', RESULTS)

    expect(prompt).toContain('System: Answer using ONLY the provided sources.')
    expect(prompt).toContain('User:\nSources:')
    expect(prompt).toContain('Question: brown animals')
  })

  it('does not leak retrieval-method info into the prompt', () => {
    const prompt = buildLlmPrompt('brown animals', RESULTS)

    expect(prompt).not.toContain('found by')
    expect(prompt).not.toContain('bm25')
    expect(prompt).not.toContain('vector')
  })
})
