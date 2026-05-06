import {
  allSettledWithConcurrency,
  MAX_CONCURRENT_UPLOADS,
  uploadSingleFile,
  pollUploadJob,
  createTrack,
  existsByAudioHash,
  uploadCoverImage,
  parseUploadMetadata,
  displayTrackTitle,
} from './api.js'
import { coverToBlob, mergeMetadata, parseAudioFileMetadata } from './audioMetadata.js'
import i18n from './i18n'

function fileStem(file) {
  return file.name.replace(/\.[^.]*$/, '')
}

function createMetadataPayload(metadata) {
  const allowed = ['title', 'artist', 'artists', 'album', 'album_artist', 'album_artists', 'release_date', 'track_number', 'lyrics', 'ext']
  return Object.fromEntries(
    allowed
      .map(key => [key, metadata?.[key]])
      .filter(([, value]) => {
        if (value == null) return false
        if (Array.isArray(value) && value.length === 0) return false
        if (typeof value === 'string' && !value.trim()) return false
        return true
      })
  )
}

export function createMetadataExt(rawTags = {}, metadata = {}) {
  const known = new Set([
    'title', 'artist', 'artists', 'album', 'album_artist', 'albumartist', 'album artist',
    'album_artists', 'release_date', 'date', 'year', 'track', 'tracknumber',
    'track_number', 'lyrics',
  ])
  const ext = {}
  for (const [key, value] of Object.entries(rawTags || {})) {
    const normalized = String(key).trim()
    if (!normalized || known.has(normalized.toLowerCase())) continue
    if (value == null) continue
    if (Array.isArray(value) && value.length === 0) continue
    if (typeof value === 'string' && !value.trim()) continue
    if (typeof value === 'object' && !(Array.isArray(value))) continue
    ext[normalized] = value
  }
  return Object.keys(ext).length ? { ...(metadata.ext || {}), ...ext } : metadata.ext
}

function logUploadError(stage, file, err, extra = {}) {
  console.error(`[upload] ${stage} failed`, {
    file: file?.name,
    ...extra,
    error: err,
  })
}

export async function uploadLocalAudioFiles({
  files,
  token,
  showToast,
  onTrackResolved = async () => {},
  progress = {
    enqueueFiles: () => {},
    startFile: () => {},
    finishFile: () => {},
  },
}) {
  if (files.length === 0) return
  progress.enqueueFiles(files.length)
  if (files.length > 1) showToast(i18n.t('upload.processingBatch', { count: files.length }))

  async function processOne(file) {
    progress.startFile(file)

    let finished = false
    function finish(ok) {
      if (finished) return
      finished = true
      progress.finishFile({ ok, file })
    }

    let parsed
    try {
      parsed = await parseAudioFileMetadata(file)
    } catch (err) {
      logUploadError('metadata parse', file, err)
      showToast(i18n.t('upload.processFailedWithReason', {
        name: file.name,
        reason: err?.message || 'metadata parse failed',
      }))
      finish(false)
      return
    }

    if (parsed.audio_hash) {
      try {
        const exists = await existsByAudioHash(parsed.audio_hash, token)
        if (exists?.exists) {
          showToast(i18n.t('upload.exists', { title: displayTrackTitle({ id: exists.track_id, title: exists.title }) }))
          await onTrackResolved(exists.track_id)
          finish(true)
          return
        }
      } catch (err) {
        logUploadError('pre-upload duplicate check', file, err, { audio_hash: parsed.audio_hash })
        // 预检失败不阻止上传；服务端上传阶段仍会做权威查重。
      }
    }

    let cleanedMetadata
    try {
      const llm = await parseUploadMetadata({
        filename_stem: fileStem(file),
        raw_tags: parsed.raw_tags || parsed.metadata || {},
      }, token)
      const merged = mergeMetadata(parsed.metadata, llm)
      merged.ext = createMetadataExt(parsed.raw_tags || parsed.metadata || {}, merged)
      cleanedMetadata = createMetadataPayload(merged)
    } catch (err) {
      logUploadError('metadata cleanup', file, err, { raw_tags: parsed.raw_tags || parsed.metadata || {} })
      showToast(i18n.t('upload.processFailedWithReason', {
        name: file.name,
        reason: err?.message || 'metadata cleanup failed',
      }))
      finish(false)
      return
    }

    let jobId
    try {
      const uploaded = await uploadSingleFile(file, token)
      jobId = uploaded.job_id
    } catch (err) {
      logUploadError('file upload', file, err)
      showToast(i18n.t('upload.uploadFailed', { name: file.name }))
      finish(false)
      return
    }

    let uploadResult
    try {
      uploadResult = await pollUploadJob(jobId, token)
    } catch (err) {
      logUploadError('upload processing', file, err, { job_id: jobId })
      if (err?.message) {
        showToast(i18n.t('upload.processFailedWithReason', { name: file.name, reason: err.message }))
      } else {
        showToast(i18n.t('upload.processFailed', { name: file.name }))
      }
      finish(false)
      return
    }

    if (uploadResult.status === 'duplicate') {
      showToast(i18n.t('upload.exists', { title: displayTrackTitle({ id: uploadResult.track_id, title: uploadResult.title }) }))
      await onTrackResolved(uploadResult.track_id)
      finish(true)
      return
    }

    let coverId = null
    const coverBlob = coverToBlob(parsed.cover)
    if (coverBlob) {
      try {
        const uploadedCover = await uploadCoverImage(coverBlob, token)
        coverId = uploadedCover.cover_id || null
      } catch (err) {
        logUploadError('cover upload', file, err)
        showToast(i18n.t('upload.writeFailed', { name: file.name }))
        finish(false)
        return
      }
    }

    try {
      const track = await createTrack({
        file_key: uploadResult.file_key,
        metadata: cleanedMetadata,
        ...(coverId ? { cover_id: coverId } : {}),
      }, token)

      if (track.status === 'added' || track.status === 'duplicate') {
        showToast(
          track.status === 'added'
            ? i18n.t('upload.added', { title: displayTrackTitle({ id: track.track_id, title: track.title }) })
            : i18n.t('upload.exists', { title: displayTrackTitle({ id: track.track_id, title: track.title }) })
        )
        await onTrackResolved(track.track_id)
        finish(true)
        return
      }
      showToast(i18n.t('upload.writeFailed', { name: file.name }))
      finish(false)
    } catch (err) {
      logUploadError('track create', file, err, { file_key: uploadResult.file_key, metadata: cleanedMetadata, cover_id: coverId })
      showToast(i18n.t('upload.writeFailed', { name: file.name }))
      finish(false)
    }
  }

  await allSettledWithConcurrency(files, MAX_CONCURRENT_UPLOADS, processOne)
}
