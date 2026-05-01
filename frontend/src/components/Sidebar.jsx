import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { useAuth } from '../contexts/AuthContext'
import { useModal } from '../contexts/ModalContext'
import { apiFetch } from '../api.js'

export default function Sidebar() {
  const { t } = useTranslation()
  const { currentView, navigate } = useNav()
  const { token, currentUser, logout } = useAuth()
  const { setShowLoginModal, setShowCreatePl } = useModal()
  const [playlists, setPlaylists] = useState([])

  useEffect(() => {
    if (token) {
      apiFetch('/library/playlists', {}, token)
        .then(data => setPlaylists(data || []))
        .catch(() => setPlaylists([]))
    } else {
      setPlaylists([])
    }
  }, [token])

  function handleUserClick() {
    if (token) logout()
    else setShowLoginModal(true)
  }

  const nav = (view, props = {}, title) => navigate(view, props, title)
  const nt = key => t(`nav.${key}`)
  const active = (v) => currentView === v ? ' active' : ''

  const avatarColor = currentUser ? 'art-' + ((currentUser.username?.charCodeAt(0) || 65) % 12 + 1) : 'art-1'
  const avatarLetter = currentUser ? (currentUser.username?.[0] || '?').toUpperCase() : '?'

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <span style={{ fontSize: 24, lineHeight: 1 }}>🎵</span>
        <span>{t('sidebar.brand')}</span>
      </div>

      <div className="sidebar-user" onClick={handleUserClick}>
        <div className={`user-avatar ${avatarColor}`}>{avatarLetter}</div>
        <div>
          <div className="user-name">{currentUser ? currentUser.username : t('sidebar.notLoggedIn')}</div>
          <div className="user-sub">{currentUser ? t('sidebar.tagline') : t('sidebar.clickLogin')}</div>
        </div>
      </div>

      <div className="sidebar-section">
        <div className={`sidebar-item${active('home')}`} onClick={() => nav('home', {}, nt('home'))}>
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M8.5 1.5a.75.75 0 00-1 0L1 7.25V14a.75.75 0 00.75.75H6a.75.75 0 00.75-.75V10h2.5v4a.75.75 0 00.75.75h4.25A.75.75 0 0015 14V7.25L8.5 1.5z"/>
          </svg>
          {t('sidebar.home')}
        </div>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-section-title">{t('sidebar.library')}</div>
        <div className={`sidebar-item${active('songs')}`} onClick={() => nav('songs', {}, nt('mySongs'))}>
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M2 2.75A.75.75 0 012.75 2h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 2.75zm0 5A.75.75 0 012.75 7h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 7.75zM2.75 12a.75.75 0 000 1.5h5.5a.75.75 0 000-1.5h-5.5z"/>
          </svg>
          {t('sidebar.mySongs')}
        </div>
        <div className={`sidebar-item${active('recent')}`} onClick={() => nav('recent', {}, nt('recent'))}>
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm8-3.5a.75.75 0 01.75.75V8.5h2.25a.75.75 0 010 1.5H8a.75.75 0 01-.75-.75V5.25A.75.75 0 018 4.5z"/>
          </svg>
          {t('sidebar.recent')}
        </div>
        <div className={`sidebar-item${active('liked')}`} onClick={() => nav('liked', {}, nt('liked'))}>
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 13.5a.75.75 0 01-.53-.22l-5.47-5.47a3.75 3.75 0 015.3-5.3L8 3.19l.7-.7a3.75 3.75 0 115.3 5.3L8.53 13.28A.75.75 0 018 13.5z"/>
          </svg>
          {t('sidebar.liked')}
        </div>
        <div className={`sidebar-item${active('albums')}`} onClick={() => nav('albums', {}, nt('albums'))}>
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zm0 3a3.5 3.5 0 110 7 3.5 3.5 0 010-7zm0 2a1.5 1.5 0 100 3 1.5 1.5 0 000-3z"/>
          </svg>
          {t('sidebar.albums')}
        </div>
        <div className={`sidebar-item${active('artists')}`} onClick={() => nav('artists', {}, nt('artists'))}>
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 0a8 8 0 100 16A8 8 0 008 0zM4.5 7.5a3.5 3.5 0 117 0 3.5 3.5 0 01-7 0z"/>
          </svg>
          {t('sidebar.artists')}
        </div>
      </div>

      <div className="sidebar-divider" />

      <div className="sidebar-section">
        <div className="sidebar-section-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingRight: 12 }}>
          <span>{t('sidebar.playlists')}</span>
          <button
            onClick={() => token ? setShowCreatePl(true) : setShowLoginModal(true)}
            title={t('sidebar.newPlaylist')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: 18, lineHeight: 1, padding: '0 2px', transition: 'color 0.15s' }}
            onMouseOver={e => e.currentTarget.style.color = 'var(--text)'}
            onMouseOut={e => e.currentTarget.style.color = 'var(--text-secondary)'}
          >+</button>
        </div>
        <div className={`sidebar-item${active('playlists')}`} onClick={() => nav('playlists', {}, nt('allPlaylists'))}>
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M2 4.25a.75.75 0 01.75-.75h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 4.25zm0 3.5a.75.75 0 01.75-.75h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 7.75zm0 3.5a.75.75 0 01.75-.75h5.5a.75.75 0 010 1.5h-5.5a.75.75 0 01-.75-.75z"/>
          </svg>
          {t('sidebar.allPlaylists')}
        </div>
        {playlists.map(pl => (
          <div
            key={pl.id}
            className={`sidebar-item${currentView === 'playlist' ? ' active' : ''}`}
            onClick={() => nav('playlist', { id: pl.id }, pl.name)}
            style={{ paddingLeft: 24 }}
          >
            <div style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: 'var(--accent)', opacity: 0.7 }} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pl.name}</span>
          </div>
        ))}
      </div>

      {currentUser?.is_admin && (
        <>
          <div className="sidebar-divider" />
          <div className="sidebar-section" style={{ marginTop: 'auto' }}>
            <div className="sidebar-section-title">{t('sidebar.system')}</div>
            <div className={`sidebar-item${active('admin-tracks')}`} onClick={() => nav('admin-tracks', {}, nt('adminTracks'))}>
              <svg viewBox="0 0 16 16" fill="currentColor">
                <path d="M2 2.75A.75.75 0 012.75 2h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 2.75zm0 5A.75.75 0 012.75 7h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 7.75zM2.75 12a.75.75 0 000 1.5h10.5a.75.75 0 000-1.5H2.75z"/>
              </svg>
              {t('sidebar.adminTracks')}
            </div>
            <div className={`sidebar-item${active('admin-users')}`} onClick={() => nav('admin-users', {}, nt('adminUsers'))}>
              <svg viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 0a8 8 0 100 16A8 8 0 008 0zM4.5 7.5a3.5 3.5 0 117 0 3.5 3.5 0 01-7 0z"/>
              </svg>
              {t('sidebar.adminUsers')}
            </div>
            <div className={`sidebar-item${active('admin-plugins')}`} onClick={() => nav('admin-plugins', {}, nt('adminPlugins'))}>
              <svg viewBox="0 0 16 16" fill="currentColor">
                <path d="M9.9 1.5a.75.75 0 01.72.53l.32 1.02a4.9 4.9 0 011.03.59l1-.36a.75.75 0 01.86.28l1 1.73a.75.75 0 01-.14.89l-.77.72c.03.23.05.46.05.7 0 .24-.02.47-.05.7l.77.72a.75.75 0 01.14.9l-1 1.72a.75.75 0 01-.86.28l-1-.36c-.32.23-.66.42-1.03.59l-.32 1.02a.75.75 0 01-.72.53H7.9a.75.75 0 01-.72-.53l-.32-1.02a4.9 4.9 0 01-1.03-.59l-1 .36a.75.75 0 01-.86-.28l-1-1.72a.75.75 0 01.14-.9l.77-.72A4.92 4.92 0 013 8c0-.24.02-.47.05-.7l-.77-.72a.75.75 0 01-.14-.89l1-1.73a.75.75 0 01.86-.28l1 .36c.32-.23.66-.42 1.03-.59l.32-1.02a.75.75 0 01.72-.53h2.8zm-1.4 4a2.5 2.5 0 100 5 2.5 2.5 0 000-5z"/>
              </svg>
              {t('sidebar.adminPlugins')}
            </div>
          </div>
        </>
      )}
    </aside>
  )
}
