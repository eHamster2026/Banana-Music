import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { apiFetch, displayTrackTitle } from '../api.js'
import TrackRow from '../components/shared/TrackRow'
import AlbumCard from '../components/shared/AlbumCard'
import ArtistCard from '../components/shared/ArtistCard'
import PlaylistCard from '../components/shared/PlaylistCard'

export default function SearchView({ query }) {
  const { t } = useTranslation()
  const { setTopbarTitle } = useNav()
  const { currentTrackId, playFromContext, setContextQueue } = usePlayer()
  const { token } = useAuth()
  const { showToast } = useToast()
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [pluginDl, setPluginDl] = useState({})

  useEffect(() => {
    setTopbarTitle(query?.trim() ? t('topbar.searchPrefix') + query : t('search.pageTitle'))
    if (!query?.trim()) { setResults(null); return }
    setLoading(true)
    apiFetch('/rest/search3?query=' + encodeURIComponent(query), {}, token)
      .then(data => {
        setResults(data)
        if (data.tracks) setContextQueue(data.tracks)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [query, token, t, setTopbarTitle])

  async function toggleLike(track) {
    if (!token) { showToast(t('search.loginFirst')); return }
    try {
      const res = await apiFetch(`/rest/toggleStar?id=${track.id}`, { method: 'POST' }, token)
      setResults(r => ({
        ...r,
        tracks: r.tracks?.map(t => t.id === track.id ? { ...t, is_liked: res.liked } : t)
      }))
      showToast(res.liked ? t('player.liked') : t('player.unliked'))
    } catch {
      showToast(t('player.likeFail'))
    }
  }

  async function downloadPluginHit(item) {
    if (!token) { showToast(t('search.loginFirst')); return }
    const key = `${item.plugin_id}:${item.source_id}`
    setPluginDl(s => ({ ...s, [key]: 'loading' }))
    try {
      const result = await apiFetch(
        '/rest/x-banana/plugins/download',
        {
          method: 'POST',
          body: JSON.stringify({
            plugin_id: item.plugin_id,
            source_id: item.source_id,
            metadata_override: {
              title: item.title,
              artist: item.artist,
              ...(Array.isArray(item.artists) && item.artists.length
                ? { artists: item.artists }
                : {}),
              album: item.album || undefined,
            },
          }),
        },
        token,
      )
      if (result.status === 'duplicate') {
        showToast(t('search.inLibrary', { title: displayTrackTitle({ id: result.track_id, title: result.title }) }))
        setPluginDl(s => ({ ...s, [key]: 'dup' }))
      } else {
        showToast(t('search.added', { title: displayTrackTitle({ id: result.track_id, title: result.title }) }))
        setPluginDl(s => ({ ...s, [key]: 'done' }))
        window.dispatchEvent(new Event('localFilesUpdated'))
      }
    } catch (err) {
      showToast(t('search.downloadFail', { msg: err.message || '—' }))
      setPluginDl(s => ({ ...s, [key]: 'idle' }))
    }
  }

  if (!query?.trim()) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🔍</div>
        <div className="empty-title">{t('search.emptyTitle')}</div>
        <div className="empty-sub">{t('search.emptySub')}</div>
      </div>
    )
  }

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>

  if (!results) return null

  const { tracks = [], artists = [], albums = [], playlists = [], plugin_hits = [] } = results
  const hasResults = tracks.length + artists.length + albums.length + playlists.length + plugin_hits.length > 0

  if (!hasResults) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🔍</div>
        <div className="empty-title">{t('search.noMatch', { query })}</div>
        <div className="empty-sub">{t('search.tryOther')}</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ padding: '24px 28px 0' }}>
        <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{t('search.resultsIntro', { query })}</div>
      </div>

      {plugin_hits.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('search.sectionPlugin')}</div>
          </div>
          <div style={{ padding: '0 28px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {plugin_hits.map(item => {
              const key = `${item.plugin_id}:${item.source_id}`
              const st = pluginDl[key] || 'idle'
              return (
                <div
                  key={key}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                    padding: '10px 14px',
                    background: 'var(--surface)',
                    borderRadius: 10,
                    border: '1px solid var(--border)',
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{item.title}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                      {item.artist} · {item.plugin_id}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={st === 'loading' || st === 'done' || st === 'dup'}
                    onClick={() => downloadPluginHit(item)}
                    style={{
                      flexShrink: 0,
                      background: 'none',
                      border: '1px solid var(--accent)',
                      borderRadius: 6,
                      color: 'var(--accent)',
                      padding: '6px 12px',
                      fontSize: 12,
                      cursor: st === 'loading' ? 'wait' : 'pointer',
                      opacity: st === 'done' || st === 'dup' ? 0.5 : 1,
                    }}
                  >
                    {st === 'loading' ? t('search.pluginLoading') : st === 'done' ? t('search.pluginDone') : st === 'dup' ? t('search.pluginDup') : t('search.pluginDownload')}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {tracks.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('search.sectionLocalTracks')}</div>
          </div>
          <div style={{ marginTop: -8 }}>
            <div className="track-list-header">
              <div style={{ textAlign: 'right', paddingRight: 14 }}>#</div>
              <div>{t('common.colTitle')}</div>
              <div>{t('common.colDuration')}</div>
              <div /><div />
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
        </div>
      )}

      {artists.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('topbar.sectionArtists')}</div>
          </div>
          <div className="artist-row">
            {artists.map(artist => (
              <ArtistCard key={artist.id} artist={artist} />
            ))}
          </div>
        </div>
      )}

      {albums.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('topbar.sectionAlbums')}</div>
          </div>
          <div className="album-row">
            {albums.map(album => (
              <AlbumCard key={album.id} album={album} />
            ))}
          </div>
        </div>
      )}

      {playlists.length > 0 && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">{t('sidebar.playlists')}</div>
          </div>
          <div className="playlist-grid">
            {playlists.map(pl => (
              <PlaylistCard key={pl.id} playlist={pl} />
            ))}
          </div>
        </div>
      )}

      <div className="bottom-spacer" />
    </div>
  )
}
