import React, { useState, useRef, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import { apiFetch, formatTrackArtists, formatAlbumArtists, displayTrackTitle } from '../api.js'
import CoverArt from './shared/CoverArt'

function getTrackColor(track) {
  return track?.album?.art_color || track?.artist?.art_color || track?.art_color || 'art-1'
}

export default function Topbar() {
  const { t, i18n } = useTranslation()
  const { topbarTitle, navStack, navFwdStack, navBack, navForward, navigate } = useNav()
  const { loadAndPlayTrack } = usePlayer()
  const { token } = useAuth()
  const [query, setQuery] = useState('')
  const [dropResults, setDropResults] = useState(null)
  const [showDrop, setShowDrop] = useState(false)
  const debounceRef = useRef(null)
  const dropRef = useRef(null)

  const search = useCallback(async (q) => {
    if (!q.trim()) { setDropResults(null); setShowDrop(false); return }
    try {
      const data = await apiFetch('/search?q=' + encodeURIComponent(q), {}, token)
      setDropResults(data)
      setShowDrop(true)
    } catch {
      setDropResults(null)
    }
  }, [token])

  function handleInput(val) {
    setQuery(val)
    clearTimeout(debounceRef.current)
    if (!val.trim()) { setDropResults(null); setShowDrop(false); return }
    debounceRef.current = setTimeout(() => search(val), 350)
  }

  function hideDropdownDelay() {
    setTimeout(() => setShowDrop(false), 180)
  }

  function goSearchPage(q) {
    if (!q.trim()) return
    setShowDrop(false)
    navigate('search', { query: q }, t('topbar.searchPrefix') + q)
  }

  const tracks = dropResults?.tracks?.slice(0, 3) || []
  const artists = dropResults?.artists?.slice(0, 2) || []
  const albums = dropResults?.albums?.slice(0, 2) || []
  const pluginHits = (dropResults?.plugin_hits || []).slice(0, 4)

  return (
    <div className="topbar">
      <div className="nav-arrows">
        <button
          className="nav-btn"
          disabled={navStack.length === 0}
          onClick={navBack}
        >
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M9.78 4.22a.75.75 0 010 1.06L7.06 8l2.72 2.72a.75.75 0 01-1.06 1.06L5.47 8.53a.75.75 0 010-1.06l3.25-3.25a.75.75 0 011.06 0z"/>
          </svg>
        </button>
        <button
          className="nav-btn"
          disabled={navFwdStack.length === 0}
          onClick={navForward}
        >
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M6.22 4.22a.75.75 0 011.06 0l3.25 3.25a.75.75 0 010 1.06L7.28 11.78a.75.75 0 01-1.06-1.06L9.44 8 6.22 4.78a.75.75 0 010-1.06z"/>
          </svg>
        </button>
        <button
          type="button"
          className="nav-btn"
          title={i18n.language === 'zh' ? t('topbar.langEn') : t('topbar.langZh')}
          onClick={() => i18n.changeLanguage(i18n.language === 'zh' ? 'en' : 'zh')}
          style={{ fontSize: 11, fontWeight: 700, width: 36 }}
        >
          {i18n.language === 'zh' ? 'EN' : t('topbar.langShortZh')}
        </button>
      </div>
      <div className="topbar-title">{topbarTitle}</div>
      <div className="search-wrap" ref={dropRef}>
        <div className="search-bar">
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M6.5 1a5.5 5.5 0 014.383 8.823l3.896 3.897a.75.75 0 01-1.06 1.06l-3.897-3.896A5.5 5.5 0 116.5 1zm0 1.5a4 4 0 100 8 4 4 0 000-8z"/>
          </svg>
          <input
            type="text"
            placeholder={t('topbar.searchPlaceholder')}
            value={query}
            onChange={e => handleInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && goSearchPage(query)}
            onBlur={hideDropdownDelay}
            onFocus={() => { if (query) setShowDrop(true) }}
            autoComplete="off"
          />
        </div>
        <div className={`search-dropdown${showDrop && dropResults ? ' show' : ''}`}>
          {pluginHits.length > 0 && (
            <>
              <div className="search-drop-section">{t('topbar.sectionOnline')}</div>
              {pluginHits.map((h, i) => (
                <div
                  key={`${h.plugin_id}-${h.source_id}-${i}`}
                  className="search-drop-item"
                  onMouseDown={() => {
                    setShowDrop(false)
                    navigate('search', { query }, t('topbar.searchPrefix') + query)
                  }}
                >
                  <CoverArt
                    coverUrl={h.cover_url}
                    colorClass="art-1"
                    className="search-drop-art"
                    alt=""
                  />
                  <div>
                    <div className="search-drop-name">{h.title}</div>
                    <div className="search-drop-meta">{h.artist} · {h.plugin_id}</div>
                  </div>
                </div>
              ))}
            </>
          )}
          {tracks.length > 0 && (
            <>
              <div className="search-drop-section">{t('topbar.sectionTracks')}</div>
              {tracks.map(tr => (
                <div key={tr.id} className="search-drop-item" onMouseDown={() => { setShowDrop(false); loadAndPlayTrack(tr.id) }}>
                  <CoverArt
                    coverUrl={tr.cover_url}
                    colorClass={getTrackColor(tr)}
                    className="search-drop-art"
                    alt={t('topbar.coverAlt', { title: displayTrackTitle(tr) })}
                  />
                  <div>
                    <div className="search-drop-name">{displayTrackTitle(tr)}</div>
                    <div className="search-drop-meta">{formatTrackArtists(tr)}</div>
                  </div>
                </div>
              ))}
            </>
          )}
          {artists.length > 0 && (
            <>
              <div className="search-drop-section">{t('topbar.sectionArtists')}</div>
              {artists.map(a => (
                <div key={a.id} className="search-drop-item" onMouseDown={() => { setShowDrop(false); navigate('artist', { id: a.id }, a.name) }}>
                  <div className={`search-drop-art round ${a.art_color || 'art-1'}`} />
                  <div>
                    <div className="search-drop-name">{a.name}</div>
                  </div>
                </div>
              ))}
            </>
          )}
          {albums.length > 0 && (
            <>
              <div className="search-drop-section">{t('topbar.sectionAlbums')}</div>
              {albums.map(a => (
                <div key={a.id} className="search-drop-item" onMouseDown={() => { setShowDrop(false); navigate('album', { id: a.id }, a.title) }}>
                  <CoverArt
                    coverUrl={a.cover_url}
                    colorClass={a.art_color || 'art-1'}
                    className="search-drop-art"
                    alt={t('topbar.coverAlt', { title: a.title })}
                  />
                  <div>
                    <div className="search-drop-name">{a.title}</div>
                    <div className="search-drop-meta">{formatAlbumArtists(a)}</div>
                  </div>
                </div>
              ))}
            </>
          )}
          {tracks.length === 0 && artists.length === 0 && albums.length === 0 && pluginHits.length === 0 && (
            <div style={{ padding: '16px', color: 'var(--text-secondary)', fontSize: 13, textAlign: 'center' }}>{t('topbar.noResults')}</div>
          )}
        </div>
      </div>
    </div>
  )
}
