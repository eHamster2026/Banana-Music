/**
 * Parse LRC-style lyrics: lines may contain one or more [mm:ss.xx] timestamps.
 * Returns sorted timed lines; plain text without valid timestamps yields isLrc: false.
 */

const TAG_RE = /\[(\d{1,3}):(\d{1,2}(?:\.\d{1,3})?)\]/g

/**
 * @param {string|null|undefined} raw
 * @returns {{ isLrc: boolean, lines: { timeSec: number, text: string }[], plain: string }}
 */
export function parseLrc(raw) {
  if (raw == null || typeof raw !== 'string') {
    return { isLrc: false, lines: [], plain: '' }
  }
  const normalized = raw.replace(/\r\n/g, '\n')
  const timed = []

  for (const line of normalized.split('\n')) {
    const matches = [...line.matchAll(TAG_RE)]
    if (matches.length === 0) continue

    for (let i = 0; i < matches.length; i++) {
      const m = matches[i]
      const mm = parseInt(m[1], 10)
      const secPart = parseFloat(m[2])
      if (Number.isNaN(mm) || Number.isNaN(secPart)) continue
      const timeSec = mm * 60 + secPart
      const start = m.index + m[0].length
      const end = i + 1 < matches.length ? matches[i + 1].index : line.length
      const text = line.slice(start, end).trim()
      if (text) timed.push({ timeSec, text })
    }
  }

  if (timed.length === 0) {
    return { isLrc: false, lines: [], plain: normalized.trimEnd() }
  }

  timed.sort((a, b) => a.timeSec - b.timeSec || a.text.localeCompare(b.text))

  return { isLrc: true, lines: timed, plain: normalized.trimEnd() }
}

/**
 * Largest index where lines[i].timeSec <= currentTime (+ small epsilon).
 * @param {{ timeSec: number }[]} lines
 * @param {number} currentTime
 * @returns {number}
 */
export function getActiveLyricIndex(lines, currentTime) {
  if (!lines?.length) return -1
  const t = currentTime + 0.05
  let lo = 0
  let hi = lines.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (lines[mid].timeSec <= t) {
      ans = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return ans
}
