import React from 'react'
import { useTranslation } from 'react-i18next'
import { fmtTime, formatTrackArtists, displayTrackTitle } from '../../api.js'
import { useModal } from '../../contexts/ModalContext'
import { useAuth } from '../../contexts/AuthContext'
import CoverArt from './CoverArt'

function getTrackColor(track) {
  return track?.album?.art_color || track?.artist?.art_color || track?.art_color || 'art-1'
}

export default function TrackRow({ track, num, contextIdx, isPlaying, onPlay, onLike }) {
  const { t } = useTranslation()
  const { openAddToPlaylist } = useModal()
  const { token } = useAuth()
  const titleShown = displayTrackTitle(track)

  return (
    <div
      className={`track-row${isPlaying ? ' now-playing' : ''}`}
      onClick={onPlay}
    >
      <div className="track-num">{isPlaying ? '♫' : num}</div>
      <div className="track-info">
        <CoverArt
          coverUrl={track.cover_url}
          colorClass={getTrackColor(track)}
          className="track-cover"
          alt={`${titleShown} ${t('player.coverAlt')}`}
        />
        <div className="track-text">
          <div className="track-title">{titleShown}</div>
          <div className="track-artist-small">{formatTrackArtists(track)}</div>
        </div>
      </div>
      <div className="track-dur">{fmtTime(track.duration_sec ?? track.duration)}</div>
      <button
        className={`track-like-btn${track.is_liked ? ' liked' : ''}`}
        onClick={e => { e.stopPropagation(); onLike && onLike() }}
        title={track.is_liked ? t('common.unlikeTooltip') : t('common.likeTooltip')}
      >
        <svg viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 13.5a.75.75 0 01-.53-.22l-5.47-5.47a3.75 3.75 0 015.3-5.3L8 3.19l.7-.7a3.75 3.75 0 115.3 5.3L8.53 13.28A.75.75 0 018 13.5z"/>
        </svg>
      </button>
      <button
        className="track-like-btn"
        style={{ opacity: 0 }}
        onClick={e => { e.stopPropagation(); if (token) openAddToPlaylist(track.id) }}
        title={t('playlist.addToPlaylist')}
        onMouseEnter={e => e.currentTarget.style.opacity = '1'}
        onMouseLeave={e => e.currentTarget.style.opacity = '0'}
      >
        <svg viewBox="0 0 16 16" fill="currentColor" style={{ width: 13, height: 13 }}>
          <path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm8-3.5a.75.75 0 01.75.75V7.5h2.25a.75.75 0 010 1.5H8.75v2.25a.75.75 0 01-1.5 0V9H5a.75.75 0 010-1.5h2.25V5.25A.75.75 0 018 4.5z"/>
        </svg>
      </button>
    </div>
  )
}
