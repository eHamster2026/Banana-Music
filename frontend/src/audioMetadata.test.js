import { describe, expect, it, vi } from 'vitest'

vi.mock('music-metadata', () => ({
  parseBlob: vi.fn(async () => ({
    common: {
      title: 'Cantata',
      artist: 'Bach',
      picture: [],
    },
    native: {},
  })),
  selectCover: vi.fn(() => {
    throw new Error('selectCover should not be called for empty picture arrays')
  }),
}))

describe('parseAudioFileMetadata', () => {
  it('handles files without embedded pictures', async () => {
    const { parseAudioFileMetadata } = await import('./audioMetadata.js')
    const file = new File(['fake'], 'sample.flac', { type: 'audio/flac' })

    const parsed = await parseAudioFileMetadata(file)

    expect(parsed.metadata.title).toBe('Cantata')
    expect(parsed.metadata.artists).toEqual(['Bach'])
    expect(parsed.cover).toBeNull()
  })
})
