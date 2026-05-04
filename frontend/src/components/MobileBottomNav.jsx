import React from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'

function isActive(currentView, group) {
  if (group === 'home') return currentView === 'home'
  if (group === 'library') return ['songs', 'local', 'recent', 'liked', 'albums', 'artists', 'album', 'artist'].includes(currentView)
  if (group === 'playlists') return ['playlists', 'playlist'].includes(currentView)
  if (group === 'search') return currentView === 'search'
  if (group === 'admin') return currentView.startsWith('admin-')
  return false
}

export default function MobileBottomNav() {
  const { t } = useTranslation()
  const { currentView, navigate } = useNav()

  const items = [
    {
      key: 'home',
      label: t('mobileNav.home'),
      view: 'home',
      title: t('mobileNav.home'),
      icon: <path d="M8.5 1.5a.75.75 0 00-1 0L1 7.25V14a.75.75 0 00.75.75H6a.75.75 0 00.75-.75V10h2.5v4a.75.75 0 00.75.75h4.25A.75.75 0 0015 14V7.25L8.5 1.5z" />,
    },
    {
      key: 'library',
      label: t('mobileNav.library'),
      view: 'songs',
      title: t('nav.mySongs'),
      icon: <path d="M2 2.75A.75.75 0 012.75 2h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 2.75zm0 5A.75.75 0 012.75 7h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 7.75zM2.75 12a.75.75 0 000 1.5h5.5a.75.75 0 000-1.5h-5.5z" />,
    },
    {
      key: 'playlists',
      label: t('mobileNav.playlists'),
      view: 'playlists',
      title: t('nav.allPlaylists'),
      icon: <path d="M2 4.25a.75.75 0 01.75-.75h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 4.25zm0 3.5a.75.75 0 01.75-.75h10.5a.75.75 0 010 1.5H2.75A.75.75 0 012 7.75zm0 3.5a.75.75 0 01.75-.75h5.5a.75.75 0 010 1.5h-5.5a.75.75 0 01-.75-.75z" />,
    },
    {
      key: 'search',
      label: t('mobileNav.search'),
      view: 'search',
      title: t('nav.search'),
      icon: <path d="M6.5 1a5.5 5.5 0 014.383 8.823l3.896 3.897a.75.75 0 01-1.06 1.06l-3.897-3.896A5.5 5.5 0 116.5 1zm0 1.5a4 4 0 100 8 4 4 0 000-8z" />,
    },
    {
      key: 'admin',
      label: t('mobileNav.admin'),
      view: 'admin-tracks',
      title: t('mobileNav.admin'),
      icon: <path d="M9.9 1.5a.75.75 0 01.72.53l.32 1.02a4.9 4.9 0 011.03.59l1-.36a.75.75 0 01.86.28l1 1.73a.75.75 0 01-.14.89l-.77.72c.03.23.05.46.05.7 0 .24-.02.47-.05.7l.77.72a.75.75 0 01.14.9l-1 1.72a.75.75 0 01-.86.28l-1-.36c-.32.23-.66.42-1.03.59l-.32 1.02a.75.75 0 01-.72.53H7.9a.75.75 0 01-.72-.53l-.32-1.02a4.9 4.9 0 01-1.03-.59l-1 .36a.75.75 0 01-.86-.28l-1-1.72a.75.75 0 01.14-.9l.77-.72A4.92 4.92 0 013 8c0-.24.02-.47.05-.7l-.77-.72a.75.75 0 01-.14-.89l1-1.73a.75.75 0 01.86-.28l1 .36c.32-.23.66-.42 1.03-.59l.32-1.02a.75.75 0 01.72-.53h2.8zm-1.4 4a2.5 2.5 0 100 5 2.5 2.5 0 000-5z" />,
    },
  ]

  return (
    <nav className="mobile-bottom-nav" aria-label={t('mobileNav.aria')}>
      {items.map(item => (
        <button
          key={item.key}
          className={`mobile-bottom-item${isActive(currentView, item.key) ? ' active' : ''}`}
          onClick={() => navigate(item.view, {}, item.title)}
          type="button"
        >
          <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            {item.icon}
          </svg>
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
  )
}
