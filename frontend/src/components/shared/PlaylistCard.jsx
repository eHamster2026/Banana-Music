import React from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../../contexts/NavContext'
import OverflowText from './OverflowText'

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
        <OverflowText className="playlist-name">{playlist.name}</OverflowText>
        <div className="playlist-meta">
          {playlist.track_count != null ? t('addToPlaylist.trackCount', { count: playlist.track_count }) : ''}
        </div>
      </div>
    </div>
  )
}
