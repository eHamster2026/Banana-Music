import React, { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { useAuth } from '../contexts/AuthContext'
import { useModal } from '../contexts/ModalContext'
import { apiFetch } from '../api.js'
import PlaylistCard from '../components/shared/PlaylistCard'
import usePageRefresh from '../hooks/usePageRefresh'

export default function AllPlaylistsView() {
  const { t } = useTranslation()
  const { setTopbarTitle } = useNav()
  const { token } = useAuth()
  const { setShowCreatePl, setShowLoginModal } = useModal()
  const [systemPlaylists, setSystemPlaylists] = useState([])
  const [userPlaylists, setUserPlaylists] = useState([])
  const [loading, setLoading] = useState(true)

  const loadPlaylists = useCallback(({ initial = false } = {}) => {
    if (initial) setLoading(true)
    const fetches = [
      apiFetch('/rest/x-banana/home').then(d => d.featured_playlists || []).catch(() => []),
    ]
    if (token) {
      fetches.push(apiFetch('/rest/getPlaylists', {}, token).catch(() => []))
    } else {
      fetches.push(Promise.resolve([]))
    }
    Promise.all(fetches).then(([sys, user]) => {
      setSystemPlaylists(sys)
      setUserPlaylists(user)
      setLoading(false)
    })
  }, [token, t, setTopbarTitle])

  useEffect(() => {
    setTopbarTitle(t('allPlaylists.pageTitle'))
    loadPlaylists({ initial: true })
  }, [t, setTopbarTitle, loadPlaylists])

  // Listen for playlist creation
  useEffect(() => {
    function reload() {
      loadPlaylists()
    }
    window.addEventListener('playlistsUpdated', reload)
    return () => window.removeEventListener('playlistsUpdated', reload)
  }, [loadPlaylists])

  usePageRefresh(loadPlaylists)

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>

  return (
    <div>
      <div style={{ padding: '24px 28px 16px' }}>
        <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.5px' }}>{t('allPlaylists.pageTitle')}</div>
      </div>

      {/* User playlists */}
      <div className="section" style={{ paddingTop: 8 }}>
        <div className="section-header">
          <div className="section-title">{t('allPlaylists.sectionMine')}</div>
          <div
            className="section-more"
            onClick={() => token ? setShowCreatePl(true) : setShowLoginModal(true)}
          >{t('allPlaylists.create')}</div>
        </div>
        {userPlaylists.length === 0 ? (
          <div style={{ color: 'var(--text-secondary)', fontSize: 14, padding: '8px 0' }}>
            {token ? t('allPlaylists.emptyMineAuthed') : t('allPlaylists.emptyMineGuest')}
          </div>
        ) : (
          <div className="pl-grid">
            {userPlaylists.map(pl => (
              <div key={pl.id} className="pl-card">
                <div className={`pl-card-art ${pl.art_color || 'art-1'}`} />
                <div className="pl-card-name">{pl.name}</div>
                <div className="pl-card-meta">{t('common.trackCount', { count: pl.track_count })}</div>
              </div>
            ))}
            <div
              className="pl-add-btn"
              onClick={() => token ? setShowCreatePl(true) : setShowLoginModal(true)}
            >
              <svg viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm8-3.5a.75.75 0 01.75.75V7.5h2.25a.75.75 0 010 1.5H8.75v2.25a.75.75 0 01-1.5 0V9H5a.75.75 0 010-1.5h2.25V5.25A.75.75 0 018 4.5z"/>
              </svg>
              <span>{t('allPlaylists.newPlaylistCard')}</span>
            </div>
          </div>
        )}
      </div>

      {/* Featured / System playlists */}
      {systemPlaylists.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('allPlaylists.sectionFeatured')}</div>
          </div>
          <div className="playlist-grid">
            {systemPlaylists.map(pl => (
              <PlaylistCard key={pl.id} playlist={pl} />
            ))}
          </div>
        </div>
      )}

      <div className="bottom-spacer" />
    </div>
  )
}
