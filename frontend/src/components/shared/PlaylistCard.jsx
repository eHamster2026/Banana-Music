import React from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../../contexts/NavContext'

export default function PlaylistCard({ playlist, onClick }) {
  const { t } = useTranslation()
  const { navigate } = useNav()

  function handleClick() {
    if (onClick) { onClick(); return }
    navigate('playlist', { id: playlist.id }, playlist.name)
  }

  return (
    <div className="playlist-card" onClick={handleClick}>
      <div className={`playlist-art ${playlist.art_color || 'art-1'}`} />
      <div style={{ minWidth: 0 }}>
        <div className="playlist-name">{playlist.name}</div>
        <div className="playlist-meta">
          {playlist.track_count != null ? t('addToPlaylist.trackCount', { count: playlist.track_count }) : ''}
        </div>
      </div>
    </div>
  )
}
