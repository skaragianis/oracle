/// <reference types="node" />
import { format } from 'node:util'
import { afterEach, beforeEach, vi } from 'vitest'

// Vue reports template/prop problems through console.warn, and dependency
// deprecations land in console.error, so neither may pass silently. Recording
// and asserting in afterEach (rather than throwing inside the spy) keeps a
// warning raised in a framework callback from being swallowed. A warning that
// fires after its test ends (e.g. an unawaited timer) is reported against the
// next test.
let calls: string[] = []

beforeEach(() => {
  calls = []
  for (const level of ['warn', 'error'] as const) {
    vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
      calls.push(`console.${level}: ${format(...args)}`)
    })
  }
})

afterEach(() => {
  vi.restoreAllMocks()
  if (calls.length > 0) {
    throw new Error(`Unexpected console output:\n${calls.join('\n')}`)
  }
})
