import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { apiFetch, fmtTime, formatAlbumArtists, updateAlbumCover, uploadCoverImage } from '../api.js'
import TrackRow from '../components/shared/TrackRow'
import CoverArt from '../components/shared/CoverArt'
import usePageRefresh from '../hooks/usePageRefresh'

export default function AlbumView({ id }) {
  const { t } = useTranslation()
  const { setTopbarTitle, navigate } = useNav()
  const { currentTrackId, playFromContext, setContextQueue } = usePlayer()
  const { token } = useAuth()
  const { showToast } = useToast()
  const [album, setAlbum]       = useState(null)
  const [loading, setLoading]   = useState(true)
  const [inLibrary, setInLibrary] = useState(false)
  const [coverUploading, setCoverUploading] = useState(false)
  const coverInputRef = useRef(null)

  const loadAlbum = useCallback(({ initial = false } = {}) => {
    if (!id) return
    if (initial) setLoading(true)
    apiFetch('/rest/getAlbum?id=' + id, {}, token)
      .then(data => {
        setAlbum(data)
        setTopbarTitle(data.title)
        setContextQueue(data.tracks || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [id, token, setTopbarTitle, setContextQueue])

  const loadLibraryState = useCallback(() => {
    if (!id || !token) return
    apiFetch('/rest/getStarred2?includeMeta=true', {}, token)
      .then(d => setInLibrary((d.albums || []).some(album => String(album.id) === String(id))))
      .catch(() => {})
  }, [id, token])

  const refreshAlbum = useCallback(() => {
    loadAlbum()
    loadLibraryState()
  }, [loadAlbum, loadLibraryState])

  useEffect(() => {
    loadAlbum({ initial: true })
  }, [loadAlbum])

  useEffect(() => {
    loadLibraryState()
  }, [loadLibraryState])

  usePageRefresh(refreshAlbum, { enabled: Boolean(id) })

  async function toggleAlbumLibrary() {
    if (!token) { showToast(t('common.loginFirst')); return }
    try {
      const res = await apiFetch('/rest/toggleStar?albumId=' + id, { method: 'POST' }, token)
      setInLibrary(res.in_library)
      showToast(res.in_library ? t('albums.addToLiked') : t('albums.removeFromLiked'))
    } catch {
      showToast(t('common.actionFailed'))
    }
  }

  async function toggleLike(track) {
    if (!token) { showToast(t('common.loginFirst')); return }
    try {
      const res = await apiFetch(`/rest/toggleStar?id=${track.id}`, { method: 'POST' }, token)
      setAlbum(a => ({
        ...a,
        tracks: a.tracks.map(t => t.id === track.id ? { ...t, is_liked: res.liked } : t)
      }))
      showToast(res.liked ? t('common.liked') : t('common.unliked'))
    } catch {
      showToast(t('common.actionFailed'))
    }
  }

  function openCoverPicker() {
    if (!token) { showToast(t('common.loginFirst')); return }
    coverInputRef.current?.click()
  }

  async function handleCoverSelected(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!token) { showToast(t('common.loginFirst')); return }

    setCoverUploading(true)
    try {
      const uploaded = await uploadCoverImage(file, token)
      const updated = await updateAlbumCover(id, uploaded.cover_id, token)
      setAlbum(current => current ? { ...current, ...updated, tracks: current.tracks } : current)
      showToast(t('albums.coverUpdated'))
    } catch (err) {
      console.error('Album cover upload failed', err)
      showToast(t('albums.coverUpdateFailed'))
    } finally {
      setCoverUploading(false)
    }
  }

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>
  if (!album) return <div className="empty-state"><div className="empty-title">{t('albums.notFound')}</div></div>

  const tracks = album.tracks || []
  const totalDur = tracks.reduce((s, t) => s + (t.duration_sec ?? t.duration ?? 0), 0)
  const albumArtistLine = formatAlbumArtists(album)
  const artistName = album.artist?.name || album.artist || ''
  const artistId   = album.artist?.id
  const year       = album.release_date?.slice(0, 4) || album.year || null

  return (
    <div>
      <div className="detail-header">
        <div className="detail-art-wrap">
          <CoverArt
            coverUrl={album.cover_url}
            colorClass={album.art_color || 'art-1'}
            className="detail-art"
            alt={`${album.title} ${t('common.coverAlt')}`}
          />
          {!album.cover_url && (
            <>
              <button
                className="detail-cover-upload"
                type="button"
                onClick={openCoverPicker}
                disabled={coverUploading}
                title={t('albums.uploadCover')}
                aria-label={t('albums.uploadCover')}
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M2.5 6.5h2l1.2-2h4.6l1.2 2h2a1 1 0 011 1v5a1 1 0 01-1 1h-11a1 1 0 01-1-1v-5a1 1 0 011-1z"/>
                  <circle cx="8" cy="10" r="2.25"/>
                </svg>
              </button>
              <input
                ref={coverInputRef}
                className="detail-cover-input"
                type="file"
                accept="image/*"
                onChange={handleCoverSelected}
              />
            </>
          )}
        </div>
        <div className="detail-info">
          <div className="detail-type">{t('albums.typeLabel')}</div>
          <div className="detail-title">{album.title}</div>
          <div className="detail-meta">
            <span
              style={{ cursor: 'pointer', color: 'var(--accent)' }}
              onClick={() => artistId && navigate('artist', { id: artistId }, artistName)}
            >{albumArtistLine}</span>
            {year && <span> · {year}</span>}
            <span> · {t('albums.trackCount', { count: tracks.length })} · {fmtTime(totalDur)}</span>
          </div>
          <div className="detail-actions">
            <button className="btn-primary" onClick={() => { setContextQueue(tracks); playFromContext(0) }}>
              <svg viewBox="0 0 16 16" fill="currentColor">
                <path d="M3.5 2.5l10 5.5-10 5.5z"/>
              </svg>
              {t('common.play')}
            </button>
            <button className="btn-secondary" onClick={() => { setContextQueue(tracks); playFromContext(Math.floor(Math.random() * tracks.length)) }}>
              {t('common.shuffle')}
            </button>
            <button
              className={`detail-lib-btn${inLibrary ? ' active' : ''}`}
              onClick={toggleAlbumLibrary}
              title={inLibrary ? t('albums.saved') : t('albums.save')}
            >
              <svg viewBox="0 0 16 16" fill={inLibrary ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth={inLibrary ? 0 : 1.5}>
                <path d="M8 13.5a.75.75 0 01-.53-.22l-5.47-5.47a3.75 3.75 0 015.3-5.3L8 3.19l.7-.7a3.75 3.75 0 115.3 5.3L8.53 13.28A.75.75 0 018 13.5z"/>
              </svg>
              {inLibrary ? t('albums.saved') : t('albums.save')}
            </button>
          </div>
        </div>
      </div>

      <div className="track-list-wrap">
        <div className="track-list-header">
          <div style={{ textAlign: 'right', paddingRight: 14 }}>#</div>
          <div>{t('common.colTitle')}</div>
          <div>{t('common.colDuration')}</div>
          <div />
          <div />
          <div />
          <div />
          <div />
        </div>
        {tracks.map((track, i) => (
          <TrackRow
            key={track.id}
            track={track}
            num={i + 1}
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
