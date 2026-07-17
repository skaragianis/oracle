import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { copyText } from '../src/clipboard'

const writeTextMock = vi.fn()
const execCommandMock = vi.fn()
let originalClipboard: Clipboard | undefined

beforeEach(() => {
  writeTextMock.mockReset().mockResolvedValue(undefined)
  execCommandMock.mockReset().mockReturnValue(true)
  originalClipboard = navigator.clipboard
  document.execCommand = execCommandMock
})

afterEach(() => {
  Object.defineProperty(navigator, 'clipboard', {
    value: originalClipboard,
    configurable: true,
  })
})

describe('copyText', () => {
  it('uses navigator.clipboard when it is available', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      configurable: true,
    })

    await copyText('hello')

    expect(writeTextMock).toHaveBeenCalledWith('hello')
    expect(execCommandMock).not.toHaveBeenCalled()
  })

  it('falls back to execCommand when navigator.clipboard is unavailable', async () => {
    // Reaching the app over plain HTTP from another machine leaves this
    // undefined — the browser only exposes it in a secure context.
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })

    await copyText('hello')

    expect(execCommandMock).toHaveBeenCalledWith('copy')
  })

  it('falls back to execCommand when navigator.clipboard.writeText rejects', async () => {
    writeTextMock.mockRejectedValue(new Error('denied'))
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      configurable: true,
    })

    await copyText('hello')

    expect(execCommandMock).toHaveBeenCalledWith('copy')
  })

  it('throws when execCommand also fails', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    execCommandMock.mockReturnValue(false)

    await expect(copyText('hello')).rejects.toThrow()
  })
})
