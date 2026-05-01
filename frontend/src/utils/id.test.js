import { afterEach, describe, expect, it, vi } from 'vitest'
import { createUuid } from './id.js'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

describe('createUuid', () => {
  const originalCrypto = globalThis.crypto

  afterEach(() => {
    vi.restoreAllMocks()
    Object.defineProperty(globalThis, 'crypto', {
      configurable: true,
      value: originalCrypto,
    })
  })

  it('uses native randomUUID when available', () => {
    Object.defineProperty(globalThis, 'crypto', {
      configurable: true,
      value: { randomUUID: vi.fn(() => 'native-id') },
    })

    expect(createUuid()).toBe('native-id')
  })

  it('falls back to getRandomValues', () => {
    Object.defineProperty(globalThis, 'crypto', {
      configurable: true,
      value: {
        getRandomValues(bytes) {
          for (let i = 0; i < bytes.length; i += 1) bytes[i] = i
          return bytes
        },
      },
    })

    expect(createUuid()).toMatch(UUID_RE)
    expect(createUuid()).toBe('00010203-0405-4607-8809-0a0b0c0d0e0f')
  })

  it('falls back when Web Crypto is unavailable', () => {
    Object.defineProperty(globalThis, 'crypto', {
      configurable: true,
      value: undefined,
    })
    vi.spyOn(Math, 'random').mockReturnValue(0)

    expect(createUuid()).toBe('00000000-0000-4000-8000-000000000000')
  })
})
