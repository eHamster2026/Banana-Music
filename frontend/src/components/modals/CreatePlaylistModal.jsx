import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useModal } from '../../contexts/ModalContext'
import { useAuth } from '../../contexts/AuthContext'
import { useToast } from '../../contexts/ToastContext'
import { apiFetch } from '../../api.js'

const COLORS = ['art-1','art-2','art-3','art-4','art-5','art-6','art-7','art-8']

export default function CreatePlaylistModal() {
  const { t } = useTranslation()
  const { showCreatePl, setShowCreatePl } = useModal()
  const { token } = useAuth()
  const { showToast } = useToast()
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [color, setColor] = useState('art-1')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (!showCreatePl) return null

  function close() {
    setShowCreatePl(false)
    setName(''); setDesc(''); setColor('art-1'); setError('')
  }

  async function doCreate() {
    if (!name.trim()) { setError(t('createPlaylist.nameRequired')); return }
    setError('')
    setLoading(true)
    try {
      await apiFetch('/playlists', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), description: desc.trim(), art_color: color }),
      }, token)
      showToast(t('createPlaylist.created', { name: name.trim() }))
      // Trigger sidebar reload
      window.dispatchEvent(new Event('playlistsUpdated'))
      close()
    } catch (e) {
      setError(e.message || t('createPlaylist.createFailed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && close()}>
      <div className="modal">
        <button className="modal-close" onClick={close}>×</button>
        <div className="modal-title" style={{ textAlign: 'left', marginBottom: 4 }}>{t('createPlaylist.title')}</div>
        <div className="modal-sub" style={{ textAlign: 'left', marginBottom: 20 }}>{t('createPlaylist.sub')}</div>
        <div className="modal-field">
          <label>{t('createPlaylist.nameLabel')}</label>
          <input
            type="text"
            placeholder={t('createPlaylist.namePlaceholder')}
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && doCreate()}
          />
        </div>
        <div className="modal-field">
          <label>{t('createPlaylist.descLabel')}</label>
          <textarea
            rows={2}
            placeholder={t('createPlaylist.descPlaceholder')}
            value={desc}
            onChange={e => setDesc(e.target.value)}
          />
        </div>
        <div className="modal-field">
          <label>{t('createPlaylist.colorLabel')}</label>
          <div className="color-picker">
            {COLORS.map(c => (
              <div
                key={c}
                className={`color-dot ${c}${color === c ? ' selected' : ''}`}
                onClick={() => setColor(c)}
              />
            ))}
          </div>
        </div>
        <div className="modal-error">{error}</div>
        <button className="modal-submit" disabled={loading} onClick={doCreate}>
          {loading ? t('createPlaylist.creating') : t('createPlaylist.createBtn')}
        </button>
      </div>
    </div>
  )
}
