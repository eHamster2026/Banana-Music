import { describe, expect, it } from 'vitest'
import { createMetadataExt } from './localUpload.js'

describe('createMetadataExt', () => {
  it('keeps unknown scalar tags and excludes mapped metadata fields', () => {
    const ext = createMetadataExt({
      TITLE: 'Cantata',
      ARTIST: 'Bach',
      CATALOGNUMBER: 'BWV 2',
      RATING: 5,
      EMPTY: '',
      OBJECT: { ignored: true },
    })

    expect(ext).toEqual({
      CATALOGNUMBER: 'BWV 2',
      RATING: 5,
    })
  })
})
