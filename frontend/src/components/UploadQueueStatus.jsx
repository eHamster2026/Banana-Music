import React from 'react'
import { useTranslation } from 'react-i18next'
import { useUploadQueue } from '../contexts/UploadQueueContext'

export default function UploadQueueStatus() {
  const { t } = useTranslation()
  const { status } = useUploadQueue()
  if (status.total === 0) return null

  const resolved = status.completed + status.failed
  const progress = status.total > 0 ? Math.round((resolved / status.total) * 100) : 0

  return (
    <div className="upload-queue-card">
      <div className="upload-queue-head">
        <strong>{t('upload.queueTitle')}</strong>
        <span>{progress}%</span>
      </div>
      <div className="upload-queue-bar">
        <div className="upload-queue-fill" style={{ width: `${progress}%` }} />
      </div>
      <div className="upload-queue-stats">
        <span>{t('upload.done')} {status.completed}/{status.total}</span>
        <span>{t('upload.waiting')} {status.waiting}</span>
        <span>{t('upload.inProgress')} {status.active}</span>
        {status.failed > 0 ? <span className="upload-queue-failed">{t('upload.failed')} {status.failed}</span> : null}
      </div>
    </div>
  )
}
