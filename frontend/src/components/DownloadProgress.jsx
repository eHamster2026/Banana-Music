import React from 'react'
import { useTranslation } from 'react-i18next'

export default function DownloadProgress({ status }) {
  const { t } = useTranslation()

  if (status === 'loading') {
    return <div className="spinner" style={{ width: 16, height: 16 }} />
  }

  if (status === 'dup') {
    return (
      <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        {t('download.inLibrary')}
      </span>
    )
  }

  if (status === 'done') {
    return (
      <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        {t('download.done')}
      </span>
    )
  }

  return null
}
