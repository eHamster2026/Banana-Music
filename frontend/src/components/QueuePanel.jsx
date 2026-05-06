import React, { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { usePlayer } from '../contexts/PlayerContext'
import { onQueueToggle } from './Player.jsx'
import { formatTrackArtists, displayTrackTitle } from '../api.js'
import CoverArt from './shared/CoverArt'
import OverflowText from './shared/OverflowText'

export default function QueuePanel() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const { queue, queueIndex, jumpTo } = usePlayer()
  const currentRef = useRef(null)

  useEffect(() => {
    const off = onQueueToggle(v => setOpen(v))
    return off
  }, [])

  // Scroll current track to center when panel opens
  useEffect(() => {
    if (!open) return
    const timer = setTimeout(() => {
      currentRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }, 60) // after CSS transition starts
    return () => clearTimeout(timer)
  }, [open])

  // Keep current track in view as it changes (while panel is open)
  useEffect(() => {
    if (!open) return
    currentRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [queueIndex, open])

  function trackArtist(track) {
    return formatTrackArtists(track) || '─'
  }

  function artColor(track) {
    return track?.album?.art_color || track?.artist?.art_color || 'art-1'
  }

  return (
    <div className={`queue-panel${open ? ' open' : ''}`}>
      <div className="queue-panel-header">
        <span>{t('queue.title')}</span>
        <button className="queue-panel-close" onClick={() => setOpen(false)}>{t('queue.close')}</button>
      </div>

      <div className="queue-panel-list">
        {queue.length === 0 && (
          <div className="queue-panel-empty">{t('queue.empty')}</div>
        )}

        {queue.map((track, idx) => {
          const isCurrent = idx === queueIndex
          const isPast    = idx < queueIndex
          const relPos    = idx - queueIndex  // negative = past, 0 = current, positive = upcoming
          const titleShown = displayTrackTitle(track)

          return (
            <div
              key={`${track.id}-${idx}`}
              ref={isCurrent ? currentRef : null}
              className={
                'queue-panel-item' +
                (isCurrent ? ' current' : '') +
                (isPast    ? ' history' : '')
              }
              onClick={() => { if (!isCurrent) jumpTo(idx) }}
            >
              {/* Position indicator */}
              <div className="queue-panel-pos">
                {isCurrent
                  ? <svg viewBox="0 0 8 10" fill="currentColor" width="8" height="10"><path d="M0 0l8 5-8 5z"/></svg>
                  : isPast
                    ? <span className="queue-panel-check">✓</span>
                    : <span className="queue-panel-rel">+{relPos}</span>
                }
              </div>

              <CoverArt
                coverUrl={track.cover_url}
                colorClass={artColor(track)}
                className="queue-panel-thumb"
                alt={`${titleShown} ${t('player.coverAlt')}`}
              />

              <div className="queue-panel-info">
                <OverflowText className="queue-panel-title">{titleShown}</OverflowText>
                <OverflowText className="queue-panel-meta">{trackArtist(track)}</OverflowText>
              </div>
            </div>
          )
        })}

        {/* Bottom padding so last item can scroll to center */}
        {queue.length > 0 && <div style={{ height: 120 }} />}
      </div>
    </div>
  )
}
