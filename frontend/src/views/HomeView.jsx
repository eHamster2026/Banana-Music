import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { useAuth } from '../contexts/AuthContext'
import { useModal } from '../contexts/ModalContext'
import { apiFetch } from '../api.js'
import AlbumCard from '../components/shared/AlbumCard'
import ArtistCard from '../components/shared/ArtistCard'

export default function HomeView() {
  const { t } = useTranslation()
  const { navigate } = useNav()
  const { token, currentUser } = useAuth()
  const { setShowLoginModal, setShowCreatePl } = useModal()
  const [playlists, setPlaylists]   = useState([])
  const [albums, setAlbums]         = useState([])
  const [artists, setArtists]       = useState([])
  const [loading, setLoading]       = useState(true)

  useEffect(() => {
    if (!token) { setLoading(false); return }
    Promise.all([
      apiFetch('/library/playlists', {}, token).catch(() => []),
      apiFetch('/library/albums',    {}, token).catch(() => []),
      apiFetch('/library/artists',   {}, token).catch(() => []),
    ]).then(([pls, albs, arts]) => {
      setPlaylists(pls  || [])
      setAlbums(albs    || [])
      setArtists(arts   || [])
      setLoading(false)
    })
  }, [token])

  // Reload playlists when a new one is created
  useEffect(() => {
    function reload() {
      if (!token) return
      apiFetch('/library/playlists', {}, token).then(d => setPlaylists(d || []))
    }
    window.addEventListener('playlistsUpdated', reload)
    return () => window.removeEventListener('playlistsUpdated', reload)
  }, [token])

  if (!token) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🎵</div>
        <div className="empty-title">{t('home.guestTitle')}</div>
        <div className="empty-sub">{t('home.guestSub')}</div>
        <button className="empty-action" onClick={() => setShowLoginModal(true)}>{t('home.guestLogin')}</button>
      </div>
    )
  }

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>

  const hasContent = playlists.length > 0 || albums.length > 0 || artists.length > 0

  return (
    <div>
      <div style={{ padding: '24px 28px 8px' }}>
        <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.5px' }}>
          {t('home.greeting', { name: currentUser?.username })}
        </div>
      </div>

      {/* ── 我的歌单 ── */}
      <div className="section">
        <div className="section-header">
          <div className="section-title">{t('home.sectionPlaylists')}</div>
          {playlists.length > 0 && (
            <div className="section-more" onClick={() => navigate('playlists', {}, t('home.sectionPlaylists'))}>
              {t('common.viewAll')}
            </div>
          )}
        </div>
        {playlists.length === 0 ? (
          <div style={{ color: 'var(--text-secondary)', fontSize: 14, padding: '4px 0 12px' }}>
            {t('home.noPlaylists')}
            <span
              style={{ color: 'var(--accent)', cursor: 'pointer' }}
              onClick={() => setShowCreatePl(true)}
            >{t('home.createFirst')}</span>
          </div>
        ) : (
          <div className="pl-grid">
            {playlists.slice(0, 6).map(pl => (
              <div
                key={pl.id}
                className="pl-card"
                onClick={() => navigate('playlist', { id: pl.id }, pl.name)}
              >
                <div className={`pl-card-art ${pl.art_color || 'art-1'}`} />
                <div className="pl-card-name">{pl.name}</div>
                <div className="pl-card-meta">{t('common.trackCount', { count: pl.track_count })}</div>
              </div>
            ))}
            <div className="pl-add-btn" onClick={() => setShowCreatePl(true)}>
              <svg viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm8-3.5a.75.75 0 01.75.75V7.5h2.25a.75.75 0 010 1.5H8.75v2.25a.75.75 0 01-1.5 0V9H5a.75.75 0 010-1.5h2.25V5.25A.75.75 0 018 4.5z"/>
              </svg>
              <span>{t('home.newPlaylist')}</span>
            </div>
          </div>
        )}
      </div>

      {/* ── 收藏的专辑 ── */}
      {albums.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('home.sectionAlbums')}</div>
            <div className="section-more" onClick={() => navigate('albums', {}, t('albums.pageTitle'))}>{t('common.viewAll')}</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 16 }}>
            {albums.slice(0, 8).map(album => (
              <AlbumCard key={album.id} album={album} />
            ))}
          </div>
        </div>
      )}

      {/* ── 关注的艺人 ── */}
      {artists.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('home.sectionArtists')}</div>
            <div className="section-more" onClick={() => navigate('artists', {}, t('artists.pageTitle'))}>{t('common.viewAll')}</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: 16 }}>
            {artists.slice(0, 10).map(artist => (
              <ArtistCard key={artist.id} artist={artist} />
            ))}
          </div>
        </div>
      )}

      {!hasContent && (
        <div style={{ padding: '12px 28px 24px', color: 'var(--text-secondary)', fontSize: 14 }}>
          {t('home.browseHint')}
        </div>
      )}

      <div className="bottom-spacer" />
    </div>
  )
}
