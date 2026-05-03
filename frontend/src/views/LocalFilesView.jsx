import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { apiFetch } from '../api.js'
import LocalTrackRow from '../components/shared/LocalTrackRow'
import useMainScrollPager from '../hooks/useMainScrollPager'

const PAGE_SIZE = 100

export default function LocalFilesView() {
  const { t } = useTranslation()
  const { setTopbarTitle } = useNav()
  const { currentTrackId, playFromContext, setContextQueue } = usePlayer()
  const { token } = useAuth()
  const { showToast } = useToast()
  const [tracks, setTracks] = useState([])
  const [totalCount, setTotalCount] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(true)
  const loadingRef = useRef(false)
  const hasMoreRef = useRef(true)
  const skipRef = useRef(0)

  useEffect(() => {
    setTopbarTitle(t('songs.pageTitle'))
  }, [t, setTopbarTitle])

  const loadTotal = useCallback(async () => {
    const count = await apiFetch('/rest/getSongCount?local=true', {}, token)
    const parsed = Number(count)
    if (Number.isFinite(parsed)) {
      setTotalCount(parsed)
    }
  }, [token])

  const loadPage = useCallback(async ({ initial = false, replace = false } = {}) => {
    if (loadingRef.current || (!replace && !hasMoreRef.current)) return
    loadingRef.current = true
    if (initial) setLoading(true)
    else if (!replace) setLoadingMore(true)

    const skip = replace ? 0 : skipRef.current
    try {
      if (replace) {
        await loadTotal()
      }
      const data = await apiFetch(`/rest/getSongs?local=true&sort=recent&skip=${skip}&limit=${PAGE_SIZE}`, {}, token)
      const page = Array.isArray(data) ? data : []
      setTracks(prev => {
        if (replace) return page
        const seen = new Set(prev.map(t => t.id))
        const next = [...prev]
        for (const track of page) {
          if (!seen.has(track.id)) {
            seen.add(track.id)
            next.push(track)
          }
        }
        return next
      })
      skipRef.current = skip + page.length
      const more = page.length === PAGE_SIZE
      hasMoreRef.current = more
      setHasMore(more)
    } catch {
      hasMoreRef.current = false
      setHasMore(false)
    } finally {
      loadingRef.current = false
      setLoading(false)
      setLoadingMore(false)
    }
  }, [token, loadTotal])

  // 首次加载：显示 spinner
  useEffect(() => {
    skipRef.current = 0
    hasMoreRef.current = true
    setHasMore(true)
    setTracks([])
    loadPage({ initial: true, replace: true })
  }, [loadPage])

  // 静默刷新：仅更新列表，不动播放队列，不显示 spinner
  const silentRefresh = useCallback(() => {
    if (loadingRef.current) return
    hasMoreRef.current = true
    setHasMore(true)
    loadPage({ replace: true })
  }, [loadPage])

  useEffect(() => {
    window.addEventListener('localFilesUpdated', silentRefresh)
    return () => window.removeEventListener('localFilesUpdated', silentRefresh)
  }, [silentRefresh])

  useMainScrollPager({ hasMore, onLoadMore: loadPage })

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

  function openFileInput() {
    document.getElementById('localFileInput')?.click()
  }

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>

  if (tracks.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🎵</div>
        <div className="empty-title">{t('songs.emptyTitle')}</div>
        <div className="empty-sub">{t('songs.emptySub')}</div>
        <button className="empty-action" onClick={openFileInput}>
          <svg viewBox="0 0 16 16" fill="currentColor" style={{ width: 14, height: 14 }}>
            <path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm8-3.5a.75.75 0 01.75.75V7.5h2.25a.75.75 0 010 1.5H8.75v2.25a.75.75 0 01-1.5 0V9H5a.75.75 0 010-1.5h2.25V5.25A.75.75 0 018 4.5z"/>
          </svg>
          {t('songs.addFile')}
        </button>
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 28px 8px' }}>
        <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{t('common.trackCount', { count: totalCount ?? tracks.length })}</div>
        <button className="btn-secondary" style={{ padding: '7px 16px', fontSize: 13 }} onClick={openFileInput}>
          {t('songs.addFileBtn')}
        </button>
      </div>
      <div style={{ padding: '0 12px' }}>
        <div className="local-track-header">
          <div>{t('common.colTitle')}</div>
          <div>{t('common.colArtist')}</div>
          <div>{t('common.colAlbum')}</div>
          <div>{t('common.colDuration')}</div>
          <div /><div /><div /><div />
        </div>
        {tracks.map((track, i) => (
          <LocalTrackRow
            key={track.id}
            track={track}
            contextIdx={i}
            isPlaying={currentTrackId === track.id}
            onPlay={() => { setContextQueue(tracks); playFromContext(i) }}
            onLike={() => toggleLike(track)}
          />
        ))}
      </div>
      <div style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {loadingMore && <div className="spinner" />}
      </div>
      <div className="bottom-spacer" />
    </div>
  )
}
