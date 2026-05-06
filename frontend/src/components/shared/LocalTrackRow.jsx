import React from 'react'
import { useTranslation } from 'react-i18next'
import { downloadTrackUrl, fmtTime, formatTrackArtists, displayTrackTitle } from '../../api.js'
import { useModal } from '../../contexts/ModalContext'
import { useAuth } from '../../contexts/AuthContext'
import { usePlayer } from '../../contexts/PlayerContext'
import { useToast } from '../../contexts/ToastContext'
import CoverArt from './CoverArt'

function getTrackColor(track) {
  return track?.album?.art_color || track?.artist?.art_color || track?.art_color || 'art-1'
}

export default function LocalTrackRow({ track, num, contextIdx, isPlaying, onPlay, onLike, onRemove }) {
  const { t } = useTranslation()
  const { openAddToPlaylist } = useModal()
  const { token } = useAuth()
  const { playNext, appendToQueue } = usePlayer()
  const { showToast } = useToast()
  const ordered = num !== undefined

  const artistName = formatTrackArtists(track) || '─'
  const albumTitle = track.album?.title  ?? track.album  ?? ''
  const duration   = track.duration_sec  ?? track.duration ?? 0
  const titleShown = displayTrackTitle(track)
  const canDownload = Boolean(track?.stream_url?.startsWith('/resource/'))

  function handlePlayNext(e) {
    e.stopPropagation()
    playNext(track)
    showToast(t('queue.addedNext'))
  }

  function handleAppend(e) {
    e.stopPropagation()
    appendToQueue(track)
    showToast(t('queue.addedEnd'))
  }

  return (
    <div
      className={`local-track-row${ordered ? ' ordered' : ''}${isPlaying ? ' now-playing' : ''}`}
      onClick={onPlay}
    >
      {ordered && (
        <div className="track-num" style={{ paddingRight: 14 }}>
          {isPlaying
            ? <svg viewBox="0 0 16 16" fill="currentColor" style={{ width: 12, height: 12 }}><path d="M3.5 2.5l10 5.5-10 5.5z"/></svg>
            : num}
        </div>
      )}
      <div className="local-title-wrap">
        <CoverArt
          coverUrl={track.cover_url}
          colorClass={getTrackColor(track)}
          className="local-track-cover"
          alt={`${titleShown} ${t('player.coverAlt')}`}
        />
        <div className="local-title">{titleShown}</div>
      </div>
      <div className="local-cell">{artistName}</div>
      <div className="local-cell">{albumTitle}</div>
      <div className="local-cell" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{fmtTime(duration)}</div>
      <button
        className="track-like-btn"
        onClick={handlePlayNext}
        title={t('queue.playNextTooltip')}
      >
        <svg viewBox="0 0 16 16" fill="currentColor">
          <path d="M2.25 3.25a.75.75 0 011.1-.66L8.8 5.72a.75.75 0 010 1.3L3.35 10.16a.75.75 0 01-1.1-.65V3.25zm8.5-.5a.75.75 0 01.75.75v2.75h2.75a.75.75 0 010 1.5H11.5v2.75a.75.75 0 01-1.5 0V7.75H7.25a.75.75 0 010-1.5H10V3.5a.75.75 0 01.75-.75z"/>
        </svg>
      </button>
      <button
        className="track-like-btn"
        onClick={handleAppend}
        title={t('queue.appendTooltip')}
      >
        <svg viewBox="0 0 16 16" fill="currentColor">
          <path d="M2.75 3.5a.75.75 0 000 1.5h6.5a.75.75 0 000-1.5h-6.5zm0 3.75a.75.75 0 000 1.5h6.5a.75.75 0 000-1.5h-6.5zm0 3.75a.75.75 0 000 1.5h4.5a.75.75 0 000-1.5h-4.5zm9-4.75a.75.75 0 01.75.75v2.25h2.25a.75.75 0 010 1.5H12.5V13a.75.75 0 01-1.5 0v-2.25H8.75a.75.75 0 010-1.5H11V7a.75.75 0 01.75-.75z"/>
        </svg>
      </button>
      <button
        className={`track-like-btn${track.is_liked ? ' liked' : ''}`}
        onClick={e => { e.stopPropagation(); onLike && onLike() }}
        title={track.is_liked ? t('common.unlikeTooltip') : t('common.likeTooltip')}
      >
        <svg viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 13.5a.75.75 0 01-.53-.22l-5.47-5.47a3.75 3.75 0 015.3-5.3L8 3.19l.7-.7a3.75 3.75 0 115.3 5.3L8.53 13.28A.75.75 0 018 13.5z"/>
        </svg>
      </button>
      {canDownload ? (
        <a
          className="track-like-btn"
          href={downloadTrackUrl(track.id)}
          download
          target="_blank"
          rel="noreferrer"
          onClick={e => e.stopPropagation()}
          title={t('common.downloadTooltip')}
          aria-label={t('common.downloadTooltip')}
        >
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1.75a.75.75 0 01.75.75v5.19l1.72-1.72a.75.75 0 111.06 1.06l-3 3a.75.75 0 01-1.06 0l-3-3a.75.75 0 011.06-1.06l1.72 1.72V2.5A.75.75 0 018 1.75zM3.25 10a.75.75 0 01.75.75v1.5h8v-1.5a.75.75 0 011.5 0V13a.75.75 0 01-.75.75h-9.5A.75.75 0 012.5 13v-2.25a.75.75 0 01.75-.75z"/>
          </svg>
        </a>
      ) : (
        <button
          className="track-like-btn"
          disabled
          title={t('common.downloadUnavailable')}
          aria-label={t('common.downloadUnavailable')}
        >
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1.75a.75.75 0 01.75.75v5.19l1.72-1.72a.75.75 0 111.06 1.06l-3 3a.75.75 0 01-1.06 0l-3-3a.75.75 0 011.06-1.06l1.72 1.72V2.5A.75.75 0 018 1.75zM3.25 10a.75.75 0 01.75.75v1.5h8v-1.5a.75.75 0 011.5 0V13a.75.75 0 01-.75.75h-9.5A.75.75 0 012.5 13v-2.25a.75.75 0 01.75-.75z"/>
          </svg>
        </button>
      )}
      {onRemove ? (
        <button
          className="track-like-btn"
          onClick={e => { e.stopPropagation(); onRemove() }}
          title={t('playlist.removeFromPlaylist')}
          style={{ color: 'var(--text-secondary)' }}
        >
          <svg viewBox="0 0 16 16" fill="currentColor" style={{ width: 13, height: 13 }}>
            <path d="M6.5 1.75a.25.25 0 01.25-.25h2.5a.25.25 0 01.25.25V3h-3V1.75zm4.5 0V3h2.25a.75.75 0 010 1.5H2.75a.75.75 0 010-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75zM4.496 6.675a.75.75 0 10-1.492.15l.66 6.6A1.75 1.75 0 005.405 15h5.19a1.75 1.75 0 001.741-1.575l.66-6.6a.75.75 0 10-1.492-.15l-.66 6.6a.25.25 0 01-.249.225H5.405a.25.25 0 01-.249-.225l-.66-6.6z"/>
          </svg>
        </button>
      ) : (
        <button
          className="track-like-btn"
          onClick={e => { e.stopPropagation(); if (token) openAddToPlaylist(track.id) }}
          title={t('playlist.addToPlaylist')}
        >
          <svg viewBox="0 0 16 16" fill="currentColor" style={{ width: 13, height: 13 }}>
            <path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm8-3.5a.75.75 0 01.75.75V7.5h2.25a.75.75 0 010 1.5H8.75v2.25a.75.75 0 01-1.5 0V9H5a.75.75 0 010-1.5h2.25V5.25A.75.75 0 018 4.5z"/>
          </svg>
        </button>
      )}
    </div>
  )
}
