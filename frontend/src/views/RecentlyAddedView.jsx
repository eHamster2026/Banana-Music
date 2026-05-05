import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { apiFetch } from '../api.js'
import LocalTrackRow from '../components/shared/LocalTrackRow'
import useMainScrollPager from '../hooks/useMainScrollPager'
import usePageRefresh from '../hooks/usePageRefresh'

const PAGE_SIZE = 100

export default function RecentlyAddedView() {
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
    setTopbarTitle(t('recent.pageTitle'))
  }, [t, setTopbarTitle])

  const loadTotal = useCallback(async () => {
    const count = await apiFetch('/rest/getSongCount', {}, token)
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
      const data = await apiFetch(`/rest/getSongs?sort=recent&skip=${skip}&limit=${PAGE_SIZE}`, {}, token)
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

  useEffect(() => {
    skipRef.current = 0
    hasMoreRef.current = true
    setHasMore(true)
    setTracks([])
    loadPage({ initial: true, replace: true })
  }, [loadPage])

  // 静默刷新：上传新文件后自动更新列表，不影响播放
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

  usePageRefresh(silentRefresh)
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

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>

  if (tracks.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🕐</div>
        <div className="empty-title">{t('recent.emptyTitle')}</div>
        <div className="empty-sub">{t('recent.emptySub')}</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ padding: '28px 28px 16px' }}>
        <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.5px', marginBottom: 4 }}>{t('recent.pageTitle')}</div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20 }}>{t('common.trackCount', { count: totalCount ?? tracks.length })}</div>
        <div className="detail-actions" style={{ marginBottom: 4 }}>
          <button className="btn-primary" onClick={() => { setContextQueue(tracks); playFromContext(0) }}>
            <svg viewBox="0 0 16 16" fill="currentColor"><path d="M3.5 2.5l10 5.5-10 5.5z"/></svg>
            {t('common.playAll')}
          </button>
          <button className="btn-secondary" onClick={() => {
            const shuffled = [...tracks].sort(() => Math.random() - 0.5)
            setContextQueue(shuffled); playFromContext(0)
          }}>{t('common.shuffle')}</button>
        </div>
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
