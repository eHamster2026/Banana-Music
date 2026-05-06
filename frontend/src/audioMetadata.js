import { parseBlob, selectCover } from 'music-metadata'

function cleanText(value) {
  if (value == null) return ''
  if (Array.isArray(value)) return cleanText(value[0])
  return String(value).replace(/\0+$/g, '').trim()
}

function splitArtists(value) {
  if (Array.isArray(value)) {
    return value.flatMap(splitArtists)
  }
  const text = cleanText(value)
  if (!text) return []
  return text.split(/\s*(?:\/|;|,|&|、|，)\s*/).map(x => x.trim()).filter(Boolean)
}

function unique(values) {
  const seen = new Set()
  const out = []
  for (const value of values) {
    const text = cleanText(value)
    if (!text || seen.has(text)) continue
    seen.add(text)
    out.push(text)
  }
  return out
}

function parseTrackNumber(value) {
  if (typeof value === 'object' && value && Number.isFinite(value.no)) {
    return value.no > 0 ? value.no : undefined
  }
  const text = cleanText(value)
  if (!text) return undefined
  const n = Number.parseInt(text.split('/', 1)[0], 10)
  return Number.isFinite(n) && n > 0 ? n : undefined
}

function metadataFromCommon(common = {}) {
  const artists = unique([
    ...(Array.isArray(common.artists) ? common.artists : []),
    ...splitArtists(common.artist),
  ])
  const albumArtists = unique(splitArtists(common.albumartist))
  const releaseDate = cleanText(common.date || common.year)
  const lyrics = cleanText(common.lyrics)
  const out = {
    title: cleanText(common.title) || undefined,
    artist: artists[0] || undefined,
    artists,
    album: cleanText(common.album) || undefined,
    album_artist: albumArtists[0] || undefined,
    album_artists: albumArtists,
    release_date: releaseDate ? releaseDate.slice(0, 10) : undefined,
    track_number: parseTrackNumber(common.track),
    lyrics: lyrics || undefined,
  }
  return Object.fromEntries(
    Object.entries(out).filter(([, value]) => {
      if (value == null) return false
      if (Array.isArray(value) && value.length === 0) return false
      return true
    })
  )
}

function nativeTags(metadata) {
  const out = {}
  for (const group of metadata?.native ? Object.values(metadata.native) : []) {
    for (const item of group || []) {
      const id = cleanText(item.id)
      if (!id) continue
      const value = item.value
      if (value == null || value instanceof Uint8Array || typeof value === 'object') continue
      if (out[id] == null) out[id] = cleanText(value)
      else if (Array.isArray(out[id])) out[id].push(cleanText(value))
      else out[id] = [out[id], cleanText(value)]
    }
  }
  return out
}

export function mergeMetadata(base, override) {
  const out = { ...(base || {}) }
  for (const [key, value] of Object.entries(override || {})) {
    if (value == null) continue
    if (Array.isArray(value) && value.length === 0) continue
    if (typeof value === 'string' && !value.trim()) continue
    out[key] = value
  }
  if (!out.artist && Array.isArray(out.artists) && out.artists.length) {
    out.artist = out.artists[0]
  }
  return out
}

export async function parseAudioFileMetadata(file) {
  const metadata = await parseBlob(file)
  const common = metadata?.common || {}
  return {
    metadata: metadataFromCommon(common),
    raw_tags: {
      ...nativeTags(metadata),
      ...metadataFromCommon(common),
    },
    cover: selectCover(common.picture || []) || null,
    audio_hash: null,
  }
}

export function coverToBlob(cover) {
  if (!cover?.data?.length) return null
  return new Blob([cover.data], { type: cover.format || 'image/jpeg' })
}
