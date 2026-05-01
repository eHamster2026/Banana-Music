import { describe, it, expect } from 'vitest'
import { parseLrc, getActiveLyricIndex } from './lrc.js'

describe('parseLrc', () => {
  it('detects LRC and sorts by time', () => {
    const text = `[00:02.00] B\n[00:01.00] A\n`
    const { isLrc, lines } = parseLrc(text)
    expect(isLrc).toBe(true)
    expect(lines.map(l => l.text)).toEqual(['A', 'B'])
    expect(lines[0].timeSec).toBe(1)
    expect(lines[1].timeSec).toBe(2)
  })

  it('handles multiple tags on one line', () => {
    const text = `[00:00.00] first [00:05.00] second`
    const { isLrc, lines } = parseLrc(text)
    expect(isLrc).toBe(true)
    expect(lines).toHaveLength(2)
    expect(lines[0].text).toBe('first')
    expect(lines[1].text).toBe('second')
  })

  it('returns plain for non-LRC', () => {
    const text = 'Just lyrics\nno timestamps here'
    const { isLrc, plain, lines } = parseLrc(text)
    expect(isLrc).toBe(false)
    expect(lines).toEqual([])
    expect(plain).toContain('Just lyrics')
  })
})

describe('getActiveLyricIndex', () => {
  const lines = [{ timeSec: 0 }, { timeSec: 5 }, { timeSec: 10 }]

  it('returns -1 before first line', () => {
    expect(getActiveLyricIndex(lines, -1)).toBe(-1)
  })

  it('tracks current segment', () => {
    expect(getActiveLyricIndex(lines, 0)).toBe(0)
    expect(getActiveLyricIndex(lines, 4.9)).toBe(0)
    expect(getActiveLyricIndex(lines, 5)).toBe(1)
    expect(getActiveLyricIndex(lines, 99)).toBe(2)
  })
})
