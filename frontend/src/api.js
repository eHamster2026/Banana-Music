import i18n from './i18n'

const API = (window.location.protocol !== 'file:' && window.location.hostname !== '')
  ? '' : 'http://localhost:8000';

export async function apiFetch(path, opts = {}, token = null) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  if (opts.headers) Object.assign(headers, opts.headers);
  const res = await fetch(API + path, { ...opts, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw Object.assign(new Error(err.detail || 'HTTP ' + res.status), { status: res.status });
  }
  return res.json();
}

// ── 上传流程（每文件独立并行流水线） ────────────────────────

export const MAX_CONCURRENT_UPLOADS = 3

/**
 * 上传单个文件。文件存盘后立即返回，处理（转码/hash/查重）在后台进行。
 * 返回：{job_id}
 * 用 pollUploadJob(job_id) 轮询结果，state=done 后再调用 createTrack。
 */
export function uploadSingleFile(file, token) {
  const form = new FormData()
  form.append('file', file)
  return fetch(API + '/rest/x-banana/tracks/upload-file', {
    method: 'POST',
    body: form,
    headers: token ? { Authorization: 'Bearer ' + token } : {},
  }).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json() })
}

/**
 * 查询上传任务状态（单次）。
 * 返回：
 *   {state: 'pending' | 'processing'}
 *   {state: 'done', status: 'ok', file_key}
 *   {state: 'done', status: 'duplicate', track_id, title}
 *   {state: 'error', detail}
 */
export function getUploadStatus(jobId, token) {
  return apiFetch(`/rest/x-banana/tracks/upload-status/${jobId}`, {}, token)
}

export function existsByAudioHash(audioHash, token) {
  return apiFetch(`/rest/x-banana/tracks/exists-by-hash?audio_hash=${encodeURIComponent(audioHash)}`, {}, token)
}

export function uploadCoverImage(blob, token) {
  const form = new FormData()
  form.append('file', blob, 'cover')
  return fetch(API + '/rest/x-banana/tracks/covers/upload', {
    method: 'POST',
    body: form,
    headers: token ? { Authorization: 'Bearer ' + token } : {},
  }).then(async r => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({}))
      throw new Error(err.detail || 'HTTP ' + r.status)
    }
    return r.json()
  })
}

export function updateAlbumCover(albumId, coverId, token) {
  return apiFetch(`/rest/x-banana/albums/${encodeURIComponent(albumId)}/cover`, {
    method: 'PUT',
    body: JSON.stringify({ cover_id: coverId }),
  }, token)
}

export function parseUploadMetadata(body, token, pluginId = 'llm-metadata') {
  return apiFetch(`/rest/x-banana/plugins/${encodeURIComponent(pluginId)}/parse-metadata`, {
    method: 'POST',
    body: JSON.stringify(body),
  }, token)
}

/**
 * 轮询上传任务直到完成（state=done 或 error）。
 * @param {string} jobId
 * @param {string|null} token
 * @param {{intervalMs?: number, timeoutMs?: number}} [opts]
 * @returns {Promise<{state:'done', status:string, file_key?:string, track_id?:number, title?:string}>}
 */
export async function pollUploadJob(jobId, token, { intervalMs = 800, timeoutMs = 120_000 } = {}) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const s = await getUploadStatus(jobId, token)
    if (s.state === 'done') return s
    if (s.state === 'error') {
      throw Object.assign(new Error(s.detail || i18n.t('upload.jobFailed')), { status: 422 })
    }
    await new Promise(r => setTimeout(r, intervalMs))
  }
  throw Object.assign(new Error(i18n.t('upload.jobTimeout')), { status: 408 })
}

export async function allSettledWithConcurrency(items, concurrency, worker) {
  const results = new Array(items.length)
  let nextIndex = 0

  async function runWorker() {
    while (true) {
      const currentIndex = nextIndex
      nextIndex += 1
      if (currentIndex >= items.length) return

      try {
        results[currentIndex] = {
          status: 'fulfilled',
          value: await worker(items[currentIndex], currentIndex),
        }
      } catch (reason) {
        results[currentIndex] = {
          status: 'rejected',
          reason,
        }
      }
    }
  }

  const workerCount = Math.max(1, Math.min(concurrency, items.length))
  await Promise.all(Array.from({ length: workerCount }, runWorker))
  return results
}

/**
 * 根据 file_key 写库。元数据由客户端解析/清洗后提交；
 * 服务端只读取上传暂存中的 audio_hash / duration。
 * 返回 {status, track_id, title, artist, artists}
 */
export function createTrack(body, token) {
  return apiFetch('/rest/x-banana/tracks/create', {
    method: 'POST',
    body: JSON.stringify(body),
  }, token)
}

export const API_BASE = API;

/** 无内嵌标题时后端存空串，列表/播放器用曲目 id 占位（如 #66） */
export function displayTrackTitle(track) {
  if (!track) return ''
  const raw = track.title != null ? String(track.title).trim() : ''
  if (raw) return raw
  if (track.id != null && track.id !== '') return `#${track.id}`
  return ''
}

export function fmtTime(sec) {
  const s = Math.floor(sec || 0);
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

/** 主艺人 + featured_artists（与后端 Track.featured_artists 语义一致），有序去重展示名 */
export function getTrackArtistNames(track) {
  if (!track) return []
  const primary = typeof track.artist === 'string' ? track.artist : track.artist?.name
  const seen = new Set()
  const names = []
  const push = (n) => {
    const t = (n && String(n).trim()) || ''
    if (!t || seen.has(t)) return
    seen.add(t)
    names.push(t)
  }
  push(primary)
  for (const a of track.featured_artists || []) {
    push(typeof a === 'string' ? a : a?.name)
  }
  return names
}

export function formatTrackArtists(track, sep = ' / ') {
  return getTrackArtistNames(track).join(sep)
}

export function formatAlbumArtists(album, sep = ' / ') {
  if (!album) return ''
  const primary = typeof album.artist === 'string' ? album.artist : album.artist?.name
  const seen = new Set()
  const names = []
  const push = (n) => {
    const t = (n && String(n).trim()) || ''
    if (!t || seen.has(t)) return
    seen.add(t)
    names.push(t)
  }
  push(primary)
  for (const a of album.featured_artists || []) {
    push(typeof a === 'string' ? a : a?.name)
  }
  return names.join(sep)
}

export function relTime(ts) {
  if (!ts) return '';
  const diff = Date.now() - ts * 1000;
  const m = Math.floor(diff / 60000);
  if (m < 1) return i18n.t('common.justNow');
  if (m < 60) return i18n.t('common.minutesAgo', { count: m });
  const h = Math.floor(m / 60);
  if (h < 24) return i18n.t('common.hoursAgo', { count: h });
  return i18n.t('common.daysAgo', { count: Math.floor(h / 24) });
}
