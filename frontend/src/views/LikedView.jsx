import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useModal } from '../contexts/ModalContext'
import { apiFetch } from '../api.js'
import LocalTrackRow from '../components/shared/LocalTrackRow'

export default function LikedView() {
  const { t } = useTranslation()
  const { setTopbarTitle } = useNav()
  const { currentTrackId, playFromContext, setContextQueue } = usePlayer()
  const { token } = useAuth()
  const { showToast } = useToast()
  const { setShowLoginModal } = useModal()
  const [tracks, setTracks] = useState([])
  const [loading, setLoading] = useState(true)

  function loadTracks() {
    if (!token) { setLoading(false); return }
    apiFetch('/rest/getStarred2', {}, token)
      .then(data => {
        setTracks(data || [])
        setContextQueue(data || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  useEffect(() => {
    setTopbarTitle(t('liked.pageTitle'))
  }, [t, setTopbarTitle])

  useEffect(() => {
    loadTracks()
  }, [token])

  useEffect(() => {
    window.addEventListener('likedTracksUpdated', loadTracks)
    return () => window.removeEventListener('likedTracksUpdated', loadTracks)
  }, [token])

  async function toggleLike(track) {
    try {
      const res = await apiFetch(`/rest/toggleStar?id=${track.id}`, { method: 'POST' }, token)
      if (!res.liked) {
        setTracks(ts => ts.filter(t => t.id !== track.id))
        showToast(t('common.unliked'))
      } else {
        setTracks(ts => ts.map(t => t.id === track.id ? { ...t, is_liked: true } : t))
        showToast(t('common.liked'))
      }
    } catch {
      showToast(t('common.actionFailed'))
    }
  }

  if (!token) {
    return (
      <div className="empty-state">
        <div className="empty-icon">♥</div>
        <div className="empty-title">{t('liked.guestTitle')}</div>
        <div className="empty-sub">{t('liked.guestSub')}</div>
        <button className="empty-action" onClick={() => setShowLoginModal(true)}>{t('liked.guestLogin')}</button>
      </div>
    )
  }

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>

  if (tracks.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">♥</div>
        <div className="empty-title">{t('liked.emptyTitle')}</div>
        <div className="empty-sub">{t('liked.emptySub')}</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ padding: '28px 28px 16px' }}>
        <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.5px', marginBottom: 4 }}>{t('liked.pageTitle')}</div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20 }}>{t('common.trackCount', { count: tracks.length })}</div>
        <div className="detail-actions" style={{ marginBottom: 4 }}>
          <button className="btn-primary" onClick={() => { setContextQueue(tracks); playFromContext(0) }}>
            <svg viewBox="0 0 16 16" fill="currentColor"><path d="M3.5 2.5l10 5.5-10 5.5z"/></svg>
            {t('common.playAll')}
          </button>
          <button className="btn-secondary" onClick={() => {
            const shuffled = [...tracks].sort(() => Math.random() - 0.5)
            setContextQueue(shuffled); playFromContext(0)
          }}>{t('common.shuffle')}</button>
        </div>
      </div>
      <div style={{ padding: '0 12px' }}>
        <div className="local-track-header">
          <div>{t('common.colTitle')}</div>
          <div>{t('common.colArtist')}</div>
          <div>{t('common.colAlbum')}</div>
          <div>{t('common.colDuration')}</div>
          <div /><div />
        </div>
        {tracks.map((track, i) => (
          <LocalTrackRow
            key={track.id}
            track={{ ...track, is_liked: true }}
            contextIdx={i}
            isPlaying={currentTrackId === track.id}
            onPlay={() => { setContextQueue(tracks); playFromContext(i) }}
            onLike={() => toggleLike(track)}
          />
        ))}
      </div>
      <div className="bottom-spacer" />
    </div>
  )
}
