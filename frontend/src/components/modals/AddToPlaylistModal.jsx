import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useModal } from '../../contexts/ModalContext'
import { useAuth } from '../../contexts/AuthContext'
import { useToast } from '../../contexts/ToastContext'
import { apiFetch } from '../../api.js'

export default function AddToPlaylistModal() {
  const { t } = useTranslation()
  const { showAddToPl, addToPlTrackId, closeAddToPl } = useModal()
  const { token } = useAuth()
  const { showToast } = useToast()
  const [playlists, setPlaylists] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (showAddToPl && token) {
      apiFetch('/rest/getPlaylists', {}, token)
        .then(data => setPlaylists(data || []))
        .catch(() => setPlaylists([]))
    }
  }, [showAddToPl, token])

  if (!showAddToPl) return null

  async function addToPlaylist(plId, plName) {
    setError('')
    setLoading(true)
    try {
      await apiFetch('/rest/addToPlaylist?id=' + plId, {
        method: 'POST',
        body: JSON.stringify({ track_id: addToPlTrackId }),
      }, token)
      showToast(t('addToPlaylist.addedTo', { name: plName }))
      window.dispatchEvent(new CustomEvent('playlistTracksUpdated', { detail: { id: plId } }))
      closeAddToPl()
    } catch (e) {
      setError(e.message || t('addToPlaylist.addFailed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && closeAddToPl()}>
      <div className="modal" style={{ width: 320 }}>
        <button className="modal-close" onClick={closeAddToPl}>×</button>
        <div className="modal-title" style={{ textAlign: 'left', marginBottom: 16 }}>{t('addToPlaylist.title')}</div>
        <div style={{ maxHeight: 280, overflowY: 'auto' }}>
          {playlists.length === 0 && (
            <div style={{ padding: '20px 0', textAlign: 'center', color: 'var(--text-secondary)', fontSize: 13 }}>
              {t('addToPlaylist.noPlaylists')}
            </div>
          )}
          {playlists.map(pl => (
            <div
              key={pl.id}
              className="search-drop-item"
              style={{ cursor: loading ? 'not-allowed' : 'pointer' }}
              onClick={() => !loading && addToPlaylist(pl.id, pl.name)}
            >
              <div className={`playlist-art ${pl.art_color || 'art-1'}`} style={{ width: 36, height: 36, borderRadius: 5 }} />
              <div>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{pl.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{t('addToPlaylist.trackCount', { count: pl.track_count })}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="modal-error">{error}</div>
      </div>
    </div>
  )
}
