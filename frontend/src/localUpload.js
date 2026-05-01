import {
  allSettledWithConcurrency,
  MAX_CONCURRENT_UPLOADS,
  computeFileHash,
  checkHash,
  uploadSingleFile,
  pollUploadJob,
  createTrack,
  displayTrackTitle,
} from './api.js'
import i18n from './i18n'

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

    let fileHash
    try {
      fileHash = await computeFileHash(file)
    } catch {
      showToast(i18n.t('upload.processFailed', { name: file.name }))
      finish(false)
      return
    }

    try {
      const check = await checkHash(fileHash, token)
      if (check.exists) {
        showToast(i18n.t('upload.exists', { title: displayTrackTitle({ id: check.track_id, title: check.title }) }))
        await onTrackResolved(check.track_id)
        finish(true)
        return
      }
    } catch {
      // 预检失败不阻断，继续上传让服务端兜底
    }

    let jobId
    try {
      const uploaded = await uploadSingleFile(file, fileHash, token)
      jobId = uploaded.job_id
    } catch {
      showToast(i18n.t('upload.uploadFailed', { name: file.name }))
      finish(false)
      return
    }

    let uploadResult
    try {
      uploadResult = await pollUploadJob(jobId, token)
    } catch (err) {
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

    try {
      const track = await createTrack({ file_key: uploadResult.file_key, parse_metadata: true }, token)

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
    } catch {
      showToast(i18n.t('upload.writeFailed', { name: file.name }))
      finish(false)
    }
  }

  await allSettledWithConcurrency(files, MAX_CONCURRENT_UPLOADS, processOne)
}
