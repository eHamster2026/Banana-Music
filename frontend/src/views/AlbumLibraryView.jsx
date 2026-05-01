import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { apiFetch } from '../api.js'
import AlbumCard from '../components/shared/AlbumCard'

const PAGE_SIZE = 100

export default function AlbumLibraryView() {
  const { t } = useTranslation()
  const { setTopbarTitle } = useNav()
  const [albums, setAlbums] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(true)
  const loadingRef = useRef(false)
  const hasMoreRef = useRef(true)
  const skipRef = useRef(0)
  const sentinelRef = useRef(null)

  useEffect(() => {
    setTopbarTitle(t('albums.pageTitle'))
  }, [t, setTopbarTitle])

  const loadPage = useCallback(async ({ initial = false } = {}) => {
    if (loadingRef.current || !hasMoreRef.current) return
    loadingRef.current = true
    if (initial) setLoading(true)
    else setLoadingMore(true)

    try {
      const data = await apiFetch(`/albums?skip=${skipRef.current}&limit=${PAGE_SIZE}`)
      const page = Array.isArray(data) ? data : []
      setAlbums(prev => {
        const seen = new Set(prev.map(a => a.id))
        const next = [...prev]
        for (const album of page) {
          if (!seen.has(album.id)) {
            seen.add(album.id)
            next.push(album)
          }
        }
        return next
      })
      skipRef.current += page.length
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
  }, [])

  useEffect(() => {
    loadPage({ initial: true })
  }, [loadPage])

  useEffect(() => {
    const node = sentinelRef.current
    if (!node || !hasMore) return
    const observer = new IntersectionObserver(
      entries => {
        if (entries.some(entry => entry.isIntersecting)) {
          loadPage()
        }
      },
      { rootMargin: '360px 0px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasMore, loadPage])

  if (loading) return <div className="loading-wrap"><div className="spinner" /></div>

  if (albums.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">💿</div>
        <div className="empty-title">{t('albums.emptyTitle')}</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ padding: '24px 28px 16px' }}>
        <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.5px', marginBottom: 4 }}>{t('albums.pageTitle')}</div>
        <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{t('albums.count', { count: albums.length })}</div>
      </div>
      <div style={{ padding: '0 28px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 20 }}>
          {albums.map(album => (
            <AlbumCard key={album.id} album={album} />
          ))}
        </div>
      </div>
      <div ref={sentinelRef} style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {loadingMore && <div className="spinner" />}
      </div>
      <div className="bottom-spacer" />
    </div>
  )
}
