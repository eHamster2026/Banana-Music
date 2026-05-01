import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { apiFetch, fmtTime } from '../api.js'
import LocalTrackRow from '../components/shared/LocalTrackRow'

const GRID_ORDERED = '44px 2fr 1fr 1fr 60px 44px 36px'

export default function PlaylistView({ id }) {
  const { t } = useTranslation()
  const { setTopbarTitle } = useNav()
  const { currentTrackId, playFromContext, setContextQueue } = usePlayer()
  const { token } = useAuth()
  const { showToast } = useToast()
  const [playlist, setPlaylist] = useState(null)
  const [loading, setLoading] = useState(true)

  function loadPlaylist() {
    if (!id) return
    apiFetch('/rest/getPlaylist?id=' + id, {}, token)
      .then(data => {
        setPlaylist(data)
        setTopbarTitle(data.name)
        setContextQueue(data.tracks || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  useEffect(() => {
    setLoading(true)
    loadPlaylist()
  }, [id])

  useEffect(() => {
    function onUpdate(e) {
      if (e.detail?.id === id) loadPlaylist()
    }
    window.addEventListener('playlistTracksUpdated', onUpdate)
    return () => window.removeEventListener('playlistTracksUpdated', onUpdate)
  }, [id, token])

  async function removeTrack(trackId) {
    if (!token) return
    try {
      await apiFetch(`/rest/removeFromPlaylist?id=${id}&track_id=${trackId}`, { method: 'DELETE' }, token)
      setPlaylist(p => ({
        ...p,
        tracks: p.tracks.filter(t => t.id !== trackId)
      }))
      showToast(t('playlist.removeTrack'))
    } catch (e) {
      showToast(e.message || t('playlist.removeFailed'))
    }
  }

  async function toggleLike(track) {
    if (!token) { showToast(t('common.loginFirst')); return }
    try {
      const res = await apiFetch(`/rest/toggleStar?id=${track.id}`, { method: 'POST' }, token)
      setPlaylist(p => ({
        ...p,
        tracks: p.tracks.map(t => t.id === track.id ? { ...t, is_liked: res.liked } : t)
      }))
      showToast(res.liked ? t('common.liked') : t('common.unliked'))
    } catch {
      showToast(t('common.actionFailed'))
    }
  }

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>
  if (!playlist) return <div className="empty-state"><div className="empty-title">{t('playlist.notFound')}</div></div>

  const tracks = playlist.tracks || []
  const totalDur = tracks.reduce((s, t) => s + (t.duration_sec ?? t.duration ?? 0), 0)

  return (
    <div>
      <div className="detail-header">
        <div className={`detail-art ${playlist.art_color || 'art-1'}`} />
        <div className="detail-info">
          <div className="detail-type">{playlist.is_system ? t('playlist.typeFeatured') : t('playlist.typeUser')}</div>
          <div className="detail-title">{playlist.name}</div>
          <div className="detail-meta">
            {playlist.description && <span>{playlist.description} · </span>}
            <span>{t('common.trackCount', { count: tracks.length })}{totalDur > 0 ? ` · ${fmtTime(totalDur)}` : ''}</span>
          </div>
          {tracks.length > 0 && (
            <div className="detail-actions">
              <button className="btn-primary" onClick={() => { setContextQueue(tracks); playFromContext(0) }}>
                <svg viewBox="0 0 16 16" fill="currentColor"><path d="M3.5 2.5l10 5.5-10 5.5z"/></svg>
                {t('common.play')}
              </button>
              <button className="btn-secondary" onClick={() => {
                const shuffled = [...tracks].sort(() => Math.random() - 0.5)
                setContextQueue(shuffled); playFromContext(0)
              }}>{t('common.shuffle')}</button>
            </div>
          )}
        </div>
      </div>

      {tracks.length === 0 ? (
        <div className="empty-state" style={{ padding: '40px 0' }}>
          <div className="empty-title">{t('playlist.emptyTitle')}</div>
          <div className="empty-sub">{t('playlist.emptySub')}</div>
        </div>
      ) : (
        <div style={{ padding: '0 12px' }}>
          {/* ordered header: # + title + artist + album + duration + like + add */}
          <div className="local-track-header" style={{ gridTemplateColumns: GRID_ORDERED }}>
            <div style={{ textAlign: 'right', paddingRight: 14 }}>#</div>
            <div>{t('common.colTitle')}</div>
            <div>{t('common.colArtist')}</div>
            <div>{t('common.colAlbum')}</div>
            <div>{t('common.colDuration')}</div>
            <div /><div />
          </div>
          {tracks.map((track, i) => (
            <LocalTrackRow
              key={track.id}
              track={track}
              num={i + 1}
              contextIdx={i}
              isPlaying={currentTrackId === track.id}
              onPlay={() => { setContextQueue(tracks); playFromContext(i) }}
              onLike={() => toggleLike(track)}
              onRemove={!playlist.is_system && token ? () => removeTrack(track.id) : undefined}
            />
          ))}
        </div>
      )}
      <div className="bottom-spacer" />
    </div>
  )
}
