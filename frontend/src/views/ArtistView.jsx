import React, { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { apiFetch } from '../api.js'
import AlbumCard from '../components/shared/AlbumCard'
import TrackRow from '../components/shared/TrackRow'
import usePageRefresh from '../hooks/usePageRefresh'

export default function ArtistView({ id }) {
  const { t } = useTranslation()
  const { setTopbarTitle } = useNav()
  const { currentTrackId, playTracks, setContextQueue } = usePlayer()
  const { token } = useAuth()
  const { showToast } = useToast()
  const [artist, setArtist]       = useState(null)
  const [albums, setAlbums]       = useState([])
  const [tracks, setTracks]       = useState([])
  const [loading, setLoading]     = useState(true)
  const [inLibrary, setInLibrary] = useState(false)

  const loadArtist = useCallback(({ initial = false } = {}) => {
    if (!id) return
    if (initial) setLoading(true)
    Promise.all([
      apiFetch('/rest/getArtist?id=' + id, {}, token),
      apiFetch('/rest/getArtistAlbums?id=' + id, {}, token).catch(() => []),
      apiFetch('/rest/getArtistSongs?id=' + id + '&limit=500', {}, token).catch(() => []),
    ]).then(([a, albs, trs]) => {
      setArtist(a)
      setAlbums(albs || [])
      setTracks(trs || [])
      setTopbarTitle(a.name)
      setContextQueue(trs || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [id, token, setTopbarTitle, setContextQueue])

  const loadLibraryState = useCallback(() => {
    if (!id || !token) return
    apiFetch('/rest/getStarred2?includeMeta=true', {}, token)
      .then(d => setInLibrary((d.artists || []).some(artist => String(artist.id) === String(id))))
      .catch(() => {})
  }, [id, token])

  const refreshArtist = useCallback(() => {
    loadArtist()
    loadLibraryState()
  }, [loadArtist, loadLibraryState])

  useEffect(() => {
    loadArtist({ initial: true })
  }, [loadArtist])

  useEffect(() => {
    loadLibraryState()
  }, [loadLibraryState])

  usePageRefresh(refreshArtist, { enabled: Boolean(id) })

  async function toggleArtistLibrary() {
    if (!token) { showToast(t('common.loginFirst')); return }
    try {
      const res = await apiFetch('/rest/toggleStar?artistId=' + id, { method: 'POST' }, token)
      setInLibrary(res.in_library)
      showToast(res.in_library ? t('artists.followed') : t('artists.unfollowed'))
    } catch {
      showToast(t('common.actionFailed'))
    }
  }

  async function toggleLike(track) {
    if (!token) { showToast(t('common.loginFirst')); return }
    try {
      const res = await apiFetch(`/rest/toggleStar?id=${track.id}`, { method: 'POST' }, token)
      setTracks(ts => ts.map(t => t.id === track.id ? { ...t, is_liked: res.liked } : t))
      showToast(res.liked ? t('common.liked') : t('common.unliked'))
    } catch {
      showToast(t('common.actionFailed'))
    }
  }

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>
  if (!artist) return <div className="empty-state"><div className="empty-title">{t('artists.notFound')}</div></div>

  return (
    <div>
      {/* Artist header */}
      <div style={{ position: 'relative', height: 220, overflow: 'hidden' }}>
        <div className={`${artist.art_color || 'art-1'}`} style={{ position: 'absolute', inset: 0, filter: 'blur(0px)' }} />
        <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(to bottom, rgba(0,0,0,0.2), rgba(10,10,10,0.95))' }} />
        <div style={{ position: 'absolute', bottom: 28, left: 28, right: 28, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.7)', marginBottom: 8 }}>{t('artists.typeLabel')}</div>
            <div style={{ fontSize: 42, fontWeight: 900, letterSpacing: '-1px' }}>{artist.name}</div>
            {artist.genre && <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.6)', marginTop: 6 }}>{artist.genre}</div>}
            {tracks.length > 0 && (
              <div className="detail-actions" style={{ marginTop: 18 }}>
                <button className="btn-primary" onClick={() => playTracks(tracks, 0)}>
                  <svg viewBox="0 0 16 16" fill="currentColor">
                    <path d="M3.5 2.5l10 5.5-10 5.5z"/>
                  </svg>
                  {t('common.play')}
                </button>
                <button
                  className="btn-secondary"
                  onClick={() => playTracks(tracks, Math.floor(Math.random() * tracks.length))}
                >
                  {t('common.shuffle')}
                </button>
              </div>
            )}
          </div>
          <button
            className={`detail-lib-btn${inLibrary ? ' active' : ''}`}
            onClick={toggleArtistLibrary}
            title={inLibrary ? t('artists.following') : t('artists.follow')}
            style={{ marginBottom: 4 }}
          >
            <svg viewBox="0 0 16 16" fill={inLibrary ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth={inLibrary ? 0 : 1.5}>
              <path d="M8 13.5a.75.75 0 01-.53-.22l-5.47-5.47a3.75 3.75 0 015.3-5.3L8 3.19l.7-.7a3.75 3.75 0 115.3 5.3L8.53 13.28A.75.75 0 018 13.5z"/>
            </svg>
            {inLibrary ? t('artists.following') : t('artists.follow')}
          </button>
        </div>
      </div>

      {/* Top tracks */}
      {tracks.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('artists.sectionTracks')}</div>
          </div>
          <div style={{ marginTop: -8 }}>
            <div className="track-list-header">
              <div style={{ textAlign: 'right', paddingRight: 14 }}>#</div>
              <div>{t('common.colTitle')}</div>
              <div>{t('common.colDuration')}</div>
              <div /><div /><div /><div /><div />
            </div>
            {tracks.map((track, i) => (
              <TrackRow
                key={track.id}
                track={track}
                num={i + 1}
                contextIdx={i}
                isPlaying={currentTrackId === track.id}
                onPlay={() => playTracks(tracks, i)}
                onLike={() => toggleLike(track)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Albums */}
      {albums.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('artists.sectionAlbums')}</div>
          </div>
          <div className="album-row">
            {albums.map(album => (
              <AlbumCard key={album.id} album={album} />
            ))}
          </div>
        </div>
      )}

      <div className="bottom-spacer" />
    </div>
  )
}
