import React, { useState, useEffect, useMemo, useLayoutEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { parseLrc, getActiveLyricIndex } from '../utils/lrc.js'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import { useModal } from '../contexts/ModalContext'
import { useToast } from '../contexts/ToastContext'
import { apiFetch, fmtTime, formatTrackArtists, displayTrackTitle } from '../api.js'
import CoverArt from './shared/CoverArt'
import OverflowText from './shared/OverflowText'

// Simple pub/sub for queue panel toggle
const queueListeners = new Set()
export function onQueueToggle(fn) { queueListeners.add(fn); return () => queueListeners.delete(fn) }
let _queueOpen = false
export function setQueueOpenGlobal(val) {
  _queueOpen = val
  queueListeners.forEach(fn => fn(val))
}

function getTrackColor(track) {
  return track?.album?.art_color || track?.artist?.art_color || track?.art_color || 'art-1'
}

export default function Player() {
  const { t } = useTranslation()
  const {
    currentTrack, isPlaying, isShuffle, isRepeat,
    currentTime, duration,
    togglePlay, nextTrack, prevTrack,
    toggleShuffle, toggleRepeat,
    seekTo, setVolume,
  } = usePlayer()
  const { token } = useAuth()
  const { setShowLoginModal } = useModal()
  const { showToast } = useToast()
  const [queueOpen, setQueueOpen] = useState(false)
  const [isLiked, setIsLiked] = useState(false)
  const [lyricsOpen, setLyricsOpen] = useState(false)
  const [trackDetail, setTrackDetail] = useState(null)
  const [lyricsLoading, setLyricsLoading] = useState(false)
  const [activeLyricIdx, setActiveLyricIdx] = useState(-1)
  const lyricsBodyRef = useRef(null)
  const lyricLineRefs = useRef([])

  useEffect(() => {
    setIsLiked(currentTrack?.is_liked || false)
  }, [currentTrack?.id])

  useEffect(() => {
    lyricLineRefs.current = []
  }, [currentTrack?.id])

  useEffect(() => {
    const off = onQueueToggle(v => setQueueOpen(v))
    return off
  }, [])

  useEffect(() => {
    if (!currentTrack?.id) {
      setTrackDetail(null)
      setLyricsLoading(false)
      return
    }

    let cancelled = false
    setLyricsLoading(true)
    apiFetch('/rest/getSong?id=' + currentTrack.id, {}, token)
      .then(data => {
        if (!cancelled) setTrackDetail(data)
      })
      .catch(() => {
        if (!cancelled) setTrackDetail(currentTrack)
      })
      .finally(() => {
        if (!cancelled) setLyricsLoading(false)
      })

    return () => { cancelled = true }
  }, [currentTrack?.id, token, lyricsOpen])

  async function toggleLike() {
    if (!token) { setShowLoginModal(true); return }
    if (!currentTrack) return
    try {
      const res = await apiFetch(`/rest/toggleStar?id=${currentTrack.id}`, { method: 'POST' }, token)
      setIsLiked(res.liked)
      showToast(res.liked ? t('player.liked') : t('player.unliked'))
    } catch {
      showToast(t('player.likeFail'))
    }
  }

  function handleProgressClick(e) {
    const rect = e.currentTarget.getBoundingClientRect()
    const pct = (e.clientX - rect.left) / rect.width
    seekTo(Math.max(0, Math.min(1, pct)))
  }

  function handleVolumeClick(e) {
    const rect = e.currentTarget.getBoundingClientRect()
    const pct = (e.clientX - rect.left) / rect.width
    setVolume(Math.max(0, Math.min(1, pct)))
    e.currentTarget.querySelector('.volume-fill').style.width = Math.max(0, Math.min(100, pct * 100)) + '%'
  }

  const totalDuration = (duration > 0 && isFinite(duration))
    ? duration
    : (currentTrack?.duration_sec ?? 0)
  const progress = totalDuration > 0 ? (currentTime / totalDuration) * 100 : 0
  const currentLyrics = trackDetail?.id === currentTrack?.id ? (trackDetail?.lyrics ?? currentTrack?.lyrics) : currentTrack?.lyrics
  const currentArtist = formatTrackArtists(currentTrack) || '─'

  const lrcParsed = useMemo(() => parseLrc(currentLyrics || ''), [currentLyrics])

  useEffect(() => {
    if (!lrcParsed.isLrc) {
      setActiveLyricIdx(-1)
      return
    }
    const idx = getActiveLyricIndex(lrcParsed.lines, currentTime)
    setActiveLyricIdx(prev => (prev === idx ? prev : idx))
  }, [currentTime, lrcParsed])

  useLayoutEffect(() => {
    if (!lyricsOpen || !lrcParsed.isLrc || activeLyricIdx < 0) return
    const el = lyricLineRefs.current[activeLyricIdx]
    const body = lyricsBodyRef.current
    if (!el || !body) return
    const bodyRect = body.getBoundingClientRect()
    const elRect = el.getBoundingClientRect()
    const delta = elRect.top - bodyRect.top - (body.clientHeight / 2 - elRect.height / 2)
    body.scrollTop += delta
  }, [activeLyricIdx, lyricsOpen, lrcParsed.isLrc, currentTrack?.id])

  function handleQueueToggle() {
    setQueueOpenGlobal(!_queueOpen)
  }

  return (
    <div className="player">
      {/* Left: track info */}
      <div className="player-track">
        <CoverArt
          coverUrl={currentTrack?.cover_url}
          colorClass={getTrackColor(currentTrack)}
          className="player-thumb"
          alt={currentTrack ? `${displayTrackTitle(currentTrack)} ${t('player.coverAlt')}` : t('player.coverAlt')}
        />
        <div className="player-track-info">
          <OverflowText className="player-track-name">{currentTrack ? displayTrackTitle(currentTrack) : t('player.pickTrack')}</OverflowText>
          <OverflowText className="player-track-artist">{currentArtist}</OverflowText>
        </div>
        <button
          className={`player-heart${isLiked ? ' active' : ''}`}
          onClick={toggleLike}
        >
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 13.5a.75.75 0 01-.53-.22l-5.47-5.47a3.75 3.75 0 015.3-5.3L8 3.19l.7-.7a3.75 3.75 0 115.3 5.3L8.53 13.28A.75.75 0 018 13.5z"/>
          </svg>
        </button>
      </div>

      {/* Center: controls */}
      <div className="player-controls">
        <div className="player-buttons">
          <button className={`ctrl-btn${isShuffle ? ' on' : ''}`} onClick={toggleShuffle} title={t('player.shuffle')}>
            <svg viewBox="0 0 16 16" fill="currentColor">
              <path d="M1 3.5A.75.75 0 011.75 3H4a.75.75 0 010 1.5H2.56l2.97 3 2.97-3H6.25a.75.75 0 010-1.5h2.25A.75.75 0 019.25 3v2.25a.75.75 0 01-1.5 0V4.56L4.78 7.5l2.97 2.94v-1.19a.75.75 0 011.5 0v2.25a.75.75 0 01-.75.75H6.25a.75.75 0 010-1.5h1.19l-2.97-3-2.97 3h1.06a.75.75 0 010 1.5H1.75A.75.75 0 011 12.5v-2.25a.75.75 0 011.5 0v1.19L4.47 9.5 2.5 7.5H1.75A.75.75 0 011 6.75V3.5zM10.75 3H13a.75.75 0 01.75.75v2.5a.75.75 0 01-1.5 0V4.56l-1.72 1.74a.75.75 0 11-1.06-1.06L11.19 3.5H10.75a.75.75 0 010-1.5zm2.25 7.44v-1.19a.75.75 0 011.5 0v2.5a.75.75 0 01-.75.75h-2.25a.75.75 0 010-1.5h.44L10.22 9.28a.75.75 0 111.06-1.06L13 9.94z"/>
            </svg>
          </button>
          <button className="ctrl-btn" onClick={prevTrack} title={t('player.prev')}>
            <svg viewBox="0 0 16 16" fill="currentColor">
              <path d="M3.5 3.75a.75.75 0 00-1.5 0v8.5a.75.75 0 001.5 0V8.94l6.72 3.9a.75.75 0 001.15-.63V3.75a.75.75 0 00-1.15-.63L3.5 7.06V3.75z"/>
            </svg>
          </button>
          <button className="play-btn" onClick={togglePlay}>
            <svg viewBox="0 0 16 16" fill="currentColor">
              {isPlaying
                ? <path d="M6 3.5h1.5v9H6zM8.5 3.5H10v9H8.5z"/>
                : <path d="M3.5 2.5l10 5.5-10 5.5z"/>
              }
            </svg>
          </button>
          <button className="ctrl-btn" onClick={nextTrack} title={t('player.next')}>
            <svg viewBox="0 0 16 16" fill="currentColor">
              <path d="M12.5 3.75a.75.75 0 011.5 0v8.5a.75.75 0 01-1.5 0V8.94l-6.72 3.9A.75.75 0 014.63 12V4a.75.75 0 011.15-.63L12.5 7.06V3.75z"/>
            </svg>
          </button>
          <button className={`ctrl-btn${isRepeat ? ' on' : ''}`} onClick={toggleRepeat} title={t('player.repeat')}>
            <svg viewBox="0 0 16 16" fill="currentColor">
              <path d="M1.75 8a6.25 6.25 0 0110.75-4.34L13.75 5H11a.75.75 0 000 1.5h4a.75.75 0 00.75-.75V1.75a.75.75 0 00-1.5 0V4l-1.25-1.25a7.75 7.75 0 100 10.5.75.75 0 10-1.06-1.06A6.25 6.25 0 011.75 8z"/>
            </svg>
          </button>
        </div>
        <div className="progress-bar">
          <span className="progress-time">{fmtTime(currentTime)}</span>
          <div className="progress-track" onClick={handleProgressClick}>
            <div className="progress-fill" style={{ width: progress + '%' }} />
          </div>
          <span className="progress-time">{fmtTime(totalDuration)}</span>
        </div>
      </div>

      {/* Right: volume + extras */}
      <div className="player-right">
        <button
          className={`ctrl-btn${queueOpen ? ' on' : ''}`}
          title={t('player.queue')}
          onClick={handleQueueToggle}
        >
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M1.75 3.5a.75.75 0 000 1.5h12.5a.75.75 0 000-1.5H1.75zm0 4a.75.75 0 000 1.5h8.5a.75.75 0 000-1.5h-8.5zm0 4a.75.75 0 000 1.5h5.5a.75.75 0 000-1.5h-5.5zm9.78.22a.75.75 0 00-1.06 1.06l1.47 1.47-1.47 1.47a.75.75 0 101.06 1.06l2-2a.75.75 0 000-1.06l-2-2z"/>
          </svg>
        </button>
        <button
          className={`ctrl-btn${lyricsOpen ? ' on' : ''}`}
          title={t('player.lyrics')}
          onClick={() => {
            if (!currentTrack) {
              showToast(t('player.needTrackFirst'))
              return
            }
            setLyricsOpen(v => !v)
          }}
        >
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M2.5 2A2.5 2.5 0 000 4.5v7A2.5 2.5 0 002.5 14h11a2.5 2.5 0 002.5-2.5v-7A2.5 2.5 0 0013.5 2h-11zm0 1.5h11a1 1 0 011 1v7a1 1 0 01-1 1h-11a1 1 0 01-1-1v-7a1 1 0 011-1zM4 6.25a.75.75 0 010 1.5H4a.75.75 0 010-1.5zm2.5 0h5.25a.75.75 0 010 1.5H6.5a.75.75 0 010-1.5zM4 9.25a.75.75 0 010 1.5H4a.75.75 0 010-1.5zm2.5 0h3.75a.75.75 0 010 1.5H6.5a.75.75 0 010-1.5z"/>
          </svg>
        </button>
        <div className="volume-bar">
          <button className="ctrl-btn" style={{ width: 24, height: 24 }}>
            <svg viewBox="0 0 16 16" fill="currentColor" style={{ width: 14, height: 14 }}>
              <path d="M7.5 1.5a.75.75 0 00-1.2-.6L3.55 3.5H1.75A1.75 1.75 0 000 5.25v5.5c0 .966.784 1.75 1.75 1.75h1.8l2.75 2.6a.75.75 0 001.2-.6V1.5zM6 3.65V12.35L4.05 10.5H1.75a.25.25 0 01-.25-.25v-5.5a.25.25 0 01.25-.25h2.3L6 3.65zm5.22-.42a.75.75 0 011.06 1.06A5.48 5.48 0 0114 8a5.48 5.48 0 01-1.72 3.72.75.75 0 01-1.06-1.06A3.98 3.98 0 0012.5 8a3.98 3.98 0 00-1.28-2.66zM9.56 4.79a.75.75 0 011.06 1.06A2.5 2.5 0 0111.5 8a2.5 2.5 0 01-.88 1.9.75.75 0 01-1.06-1.06A1 1 0 0010 8a1 1 0 00-.44-.85.75.75 0 010-1.36z"/>
            </svg>
          </button>
          <div className="volume-track" onClick={handleVolumeClick}>
            <div className="volume-fill" style={{ width: '70%' }} />
          </div>
        </div>
      </div>
      <div className={`lyrics-panel${lyricsOpen ? ' open' : ''}`}>
        <div className="lyrics-panel-head">
          <div>
            <div className="lyrics-panel-title">{displayTrackTitle(currentTrack) || t('player.lyricsTitle')}</div>
            <div className="lyrics-panel-artist">{currentArtist}</div>
          </div>
          <button className="lyrics-panel-close" onClick={() => setLyricsOpen(false)}>{t('player.close')}</button>
        </div>
        <div className="lyrics-panel-body" ref={lyricsBodyRef}>
          {lyricsLoading ? (
            <div className="lyrics-panel-empty">{t('player.lyricsLoading')}</div>
          ) : lrcParsed.isLrc ? (
            <div className="lyrics-lines">
              {lrcParsed.lines.map((line, i) => (
                <div
                  key={`${line.timeSec}-${i}`}
                  ref={el => { lyricLineRefs.current[i] = el }}
                  className={`lyrics-line${i === activeLyricIdx ? ' lyrics-line--active' : ''}`}
                >
                  {line.text}
                </div>
              ))}
            </div>
          ) : currentLyrics ? (
            <pre className="lyrics-panel-text">{currentLyrics}</pre>
          ) : (
            <div className="lyrics-panel-empty">{t('player.noLyrics')}</div>
          )}
        </div>
      </div>
    </div>
  )
}
