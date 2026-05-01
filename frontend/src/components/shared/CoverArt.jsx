import React from 'react'
import i18n from '../../i18n'
import { API_BASE } from '../../api.js'

function resolveCoverUrl(coverUrl) {
  if (!coverUrl) return null
  if (coverUrl.startsWith('http://') || coverUrl.startsWith('https://')) return coverUrl
  return API_BASE + coverUrl
}

export default function CoverArt({ coverUrl, colorClass = 'art-1', className = '', alt = i18n.t('common.coverAlt'), loading = 'lazy' }) {
  const src = resolveCoverUrl(coverUrl)
  if (src) {
    return <img src={src} alt={alt} className={`${className} cover-art-img`.trim()} loading={loading} />
  }
  return <div className={`${className} ${colorClass}`.trim()} aria-hidden="true" />
}
