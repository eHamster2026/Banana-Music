import React, { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useNav } from '../contexts/NavContext'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useUploadQueue } from '../contexts/UploadQueueContext'
import { apiFetch } from '../api.js'
import { uploadLocalAudioFiles } from '../localUpload.js'

const AUDIO_EXT = /\.(mp3|flac|wav|m4a|aac|ogg|ape|wma)$/i

export default function DropOverlay() {
  const { t } = useTranslation()
  const { currentView, currentViewProps } = useNav()
  const { token } = useAuth()
  const { showToast } = useToast()
  const uploadQueue = useUploadQueue()
  const [show, setShow] = useState(false)
  const leaveTimerRef = useRef(null)

  const isLocal  = currentView === 'local' || currentView === 'songs'
  const isLiked  = currentView === 'liked'
  const isPlaylist = currentView === 'playlist'
  const active = isLocal || isLiked || isPlaylist

  const overlayLabel = isLiked
    ? t('upload.dropLiked')
    : isPlaylist
      ? t('upload.dropPlaylist')
      : t('upload.dropLibrary')

  useEffect(() => {
    if (!active) return

    function onDragEnter(e) {
      e.preventDefault()
      clearTimeout(leaveTimerRef.current)
      setShow(true)
    }
    function onDragLeave(e) {
      e.preventDefault()
      // Firefox 在子元素边界处会多触发 dragleave，用延迟消抖
      leaveTimerRef.current = setTimeout(() => setShow(false), 80)
    }
    function onDragOver(e) { e.preventDefault() }

    async function onDrop(e) {
      e.preventDefault()
      clearTimeout(leaveTimerRef.current)
      setShow(false)

      const files = Array.from(e.dataTransfer.files)
        .filter(f => f.type.startsWith('audio/') || AUDIO_EXT.test(f.name))
      if (files.length === 0) { showToast(t('upload.noAudio')); return }

      // 快照视图状态（异步回调中不受导航变化影响）
      const _isLiked    = isLiked
      const _isPlaylist = isPlaylist
      const _playlistId = currentViewProps?.id

      async function addToLibrary(trackId) {
        if (_isLiked) {
          try {
            const res = await apiFetch(`/library/tracks/${trackId}/like`, { method: 'POST' }, token)
            if (res.liked === false) await apiFetch(`/library/tracks/${trackId}/like`, { method: 'POST' }, token)
            showToast(t('upload.addedToLiked'))
          } catch { showToast(t('upload.addedToLikedFail')) }
          window.dispatchEvent(new Event('likedTracksUpdated'))
        } else if (_isPlaylist && _playlistId) {
          try {
            await apiFetch(`/playlists/${_playlistId}/tracks`, {
              method: 'POST', body: JSON.stringify({ track_id: trackId }),
            }, token)
            showToast(t('upload.addedToPlaylist'))
          } catch { showToast(t('upload.addedToPlaylistFail')) }
          window.dispatchEvent(new CustomEvent('playlistTracksUpdated', { detail: { id: _playlistId } }))
        } else {
          window.dispatchEvent(new Event('localFilesUpdated'))
        }
      }

      await uploadLocalAudioFiles({
        files,
        token,
        showToast,
        progress: uploadQueue,
        onTrackResolved: addToLibrary,
      })
    }

    window.addEventListener('dragenter', onDragEnter)
    window.addEventListener('dragleave', onDragLeave)
    window.addEventListener('dragover', onDragOver)
    window.addEventListener('drop', onDrop)
    return () => {
      clearTimeout(leaveTimerRef.current)
      window.removeEventListener('dragenter', onDragEnter)
      window.removeEventListener('dragleave', onDragLeave)
      window.removeEventListener('dragover', onDragOver)
      window.removeEventListener('drop', onDrop)
    }
  }, [active, isLiked, isPlaylist, currentViewProps, token])

  if (!active) return null

  return (
    <div className={`drop-overlay${show ? ' show' : ''}`}>
      <div className="drop-overlay-box">
        <svg viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 1a.75.75 0 01.75.75v5.79l1.97-1.97a.75.75 0 111.06 1.06L8.53 9.87a.75.75 0 01-1.06 0L4.22 6.63a.75.75 0 011.06-1.06L7.25 7.54V1.75A.75.75 0 018 1zM1.5 9.5a.75.75 0 011.5 0v3h10v-3a.75.75 0 011.5 0v3.25a.75.75 0 01-.75.75H1.75a.75.75 0 01-.75-.75V9.5z"/>
        </svg>
        <p>{overlayLabel}</p>
        <span>{t('upload.supportedFormats')}</span>
      </div>
    </div>
  )
}
