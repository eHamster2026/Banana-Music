import React from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../../contexts/NavContext'
import { formatAlbumArtists } from '../../api.js'
import CoverArt from './CoverArt'
import OverflowText from './OverflowText'

export default function AlbumCard({ album, onClick }) {
  const { t } = useTranslation()
  const { navigate } = useNav()

  function handleClick() {
    if (onClick) { onClick(); return }
    navigate('album', { id: album.id }, album.title)
  }

  return (
    <div className="album-card" onClick={handleClick}>
      <div className="album-art">
        <CoverArt
          coverUrl={album.cover_url}
          colorClass={album.art_color || 'art-1'}
          className="album-art-inner"
          alt={t('topbar.coverAlt', { title: album.title })}
        />
        <div className="album-play-overlay">
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M3.5 2.5l10 5.5-10 5.5z"/>
          </svg>
        </div>
      </div>
      <OverflowText className="album-name">{album.title}</OverflowText>
      <OverflowText className="album-artist">{formatAlbumArtists(album)}</OverflowText>
    </div>
  )
}
