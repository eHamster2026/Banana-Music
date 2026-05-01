import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { apiFetch } from '../api.js'
import ArtistCard from '../components/shared/ArtistCard'

const PAGE_SIZE = 100

export default function ArtistLibraryView() {
  const { t } = useTranslation()
  const { setTopbarTitle } = useNav()
  const [artists, setArtists] = useState([])
  const [totalCount, setTotalCount] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(true)
  const loadingRef = useRef(false)
  const hasMoreRef = useRef(true)
  const skipRef = useRef(0)
  const sentinelRef = useRef(null)

  useEffect(() => {
    setTopbarTitle(t('artists.pageTitle'))
  }, [t, setTopbarTitle])

  const loadTotal = useCallback(async () => {
    const count = await apiFetch('/artists/count')
    const parsed = Number(count)
    if (Number.isFinite(parsed)) {
      setTotalCount(parsed)
    }
  }, [])

  const loadPage = useCallback(async ({ initial = false } = {}) => {
    if (loadingRef.current || !hasMoreRef.current) return
    loadingRef.current = true
    if (initial) setLoading(true)
    else setLoadingMore(true)

    try {
      if (initial) {
        await loadTotal()
      }
      const data = await apiFetch(`/artists?skip=${skipRef.current}&limit=${PAGE_SIZE}`)
      const page = Array.isArray(data) ? data : []
      setArtists(prev => {
        const seen = new Set(prev.map(a => a.id))
        const next = [...prev]
        for (const artist of page) {
          if (!seen.has(artist.id)) {
            seen.add(artist.id)
            next.push(artist)
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
  }, [loadTotal])

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

  if (artists.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🎤</div>
        <div className="empty-title">{t('artists.emptyTitle')}</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ padding: '24px 28px 16px' }}>
        <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.5px', marginBottom: 4 }}>{t('artists.pageTitle')}</div>
        <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{t('artists.count', { count: totalCount ?? artists.length })}</div>
      </div>
      <div style={{ padding: '0 28px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 24 }}>
          {artists.map(artist => (
            <ArtistCard key={artist.id} artist={artist} />
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
