import React, { createContext, useContext, useRef, useState, useEffect, useCallback } from 'react'
import { apiFetch, API_BASE } from '../api.js'
import { useAuth } from './AuthContext.jsx'
import { createUuid } from '../utils/id.js'

const PlayerContext = createContext(null)
const SYNC_POSITION_INTERVAL_MS = 5000

// ── device identity ──────────────────────────────────────────────
function getDeviceId() {
  let id = localStorage.getItem('deviceId')
  if (!id) {
    id = createUuid()
    localStorage.setItem('deviceId', id)
  }
  return id
}
const DEVICE_ID = getDeviceId()

// ── helpers ──────────────────────────────────────────────────────
function extractTracks(items) {
  return (items || [])
    .slice()
    .sort((a, b) => a.order_idx - b.order_idx)
    .map(it => it.track)
}

// ── local state persistence ───────────────────────────────────────
const LKEY = 'player_local_state'

function saveLocal(queue, queueIndex, position) {
  try {
    localStorage.setItem(LKEY, JSON.stringify({ queue, queueIndex, position }))
  } catch (_) {}
}

function loadLocal() {
  try { return JSON.parse(localStorage.getItem(LKEY) || 'null') }
  catch (_) { return null }
}

function clearLocalPlayerState() {
  try { localStorage.removeItem(LKEY) } catch (_) {}
}

/** 当前曲目是否在库中且可解析 stream（避免 DB 重置后仍用本地缓存的 id / stream_url） */
async function trackStillValid(track, token) {
  if (!track?.id || !token) return false
  try {
    await apiFetch('/rest/getStreamInfo?id=' + track.id, {}, token)
    return true
  } catch (e) {
    return false
  }
}

export function PlayerProvider({ children }) {
  const { token } = useAuth()
  const audioRef = useRef(null)

  // ── local playback state ─────────────────────────────────────
  const [queue, setQueue]           = useState([])
  const [queueIndex, setQueueIndex] = useState(-1)
  const [contextQueue, setContextQueueState] = useState([])
  const [isPlaying, setIsPlaying]   = useState(false)
  const [isShuffle, setIsShuffle]   = useState(false)
  const [isRepeat, setIsRepeat]     = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration]     = useState(0)
  const [currentTrackId, setCurrentTrackId] = useState(null)

  // ── refs (for closures in event handlers) ────────────────────
  const queueRef      = useRef(queue)
  const queueIndexRef = useRef(queueIndex)
  const isRepeatRef   = useRef(isRepeat)
  const isShuffleRef  = useRef(isShuffle)
  const tokenRef      = useRef(token)
  const isActiveDeviceRef = useRef(false)

  useEffect(() => { queueRef.current      = queue      }, [queue])
  useEffect(() => { queueIndexRef.current = queueIndex }, [queueIndex])
  useEffect(() => { isRepeatRef.current   = isRepeat   }, [isRepeat])
  useEffect(() => { isShuffleRef.current  = isShuffle  }, [isShuffle])
  useEffect(() => { tokenRef.current      = token      }, [token])

  const markActiveDevice = useCallback(() => {
    isActiveDeviceRef.current = true
  }, [])

  const markInactiveDevice = useCallback(() => {
    if (!isActiveDeviceRef.current) return
    isActiveDeviceRef.current = false
    audioRef.current?.pause()
    setIsPlaying(false)
  }, [])

  const handleCommandState = useCallback((state) => {
    if (!state) return null
    if (state.active_device && state.active_device !== DEVICE_ID) {
      markInactiveDevice()
      return false
    }
    if (state.active_device === DEVICE_ID) {
      isActiveDeviceRef.current = true
    }
    return true
  }, [markInactiveDevice])

  // ── server command dispatch ──────────────────────────────────
  const sendCommand = useCallback(async (command, extra = {}) => {
    const tok = tokenRef.current
    if (!tok) return null
    try {
      const state = await apiFetch('/rest/x-banana/queue/command', {
        method: 'POST',
        body: JSON.stringify({ command, device_id: DEVICE_ID, ...extra }),
      }, tok)
      return handleCommandState(state)
    } catch (_) {
      return null
    }
  }, [handleCommandState])

  // ── audio element setup ──────────────────────────────────────
  useEffect(() => {
    if (!audioRef.current) {
      audioRef.current = new Audio()
      audioRef.current.preload = 'metadata'
    }
    const audio = audioRef.current
    let saveTimer = null

    const onTimeUpdate = () => {
      setCurrentTime(audio.currentTime)
      // Throttle localStorage saves to once every 2 s
      if (!saveTimer) {
        saveTimer = setTimeout(() => {
          saveLocal(queueRef.current, queueIndexRef.current, audio.currentTime)
          saveTimer = null
        }, 2000)
      }
    }
    const onDurationChange = () => setDuration(audio.duration || 0)
    const onEnded          = () => handleEnded()
    const onPlay           = () => setIsPlaying(true)
    const onPause          = () => {
      setIsPlaying(false)
      // Save immediately on pause so position is accurate
      clearTimeout(saveTimer)
      saveTimer = null
      saveLocal(queueRef.current, queueIndexRef.current, audio.currentTime)
    }

    audio.addEventListener('timeupdate',     onTimeUpdate)
    audio.addEventListener('durationchange', onDurationChange)
    audio.addEventListener('ended',          onEnded)
    audio.addEventListener('play',           onPlay)
    audio.addEventListener('pause',          onPause)

    return () => {
      clearTimeout(saveTimer)
      audio.removeEventListener('timeupdate',     onTimeUpdate)
      audio.removeEventListener('durationchange', onDurationChange)
      audio.removeEventListener('ended',          onEnded)
      audio.removeEventListener('play',           onPlay)
      audio.removeEventListener('pause',          onPause)
    }
  }, [])

  // ── position heartbeat: POST response decides whether this device may keep playing.
  useEffect(() => {
    const timer = setInterval(() => {
      if (!audioRef.current || audioRef.current.paused) return
      sendCommand('sync_position', { position_sec: audioRef.current.currentTime })
    }, SYNC_POSITION_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [sendCommand])

  // ── ended handler ─────────────────────────────────────────────
  async function handleEnded() {
    if (isRepeatRef.current) {
      audioRef.current.currentTime = 0
      audioRef.current.play().catch(() => {})
      return
    }
    const q   = queueRef.current
    const idx = queueIndexRef.current
    if (isShuffleRef.current && q.length > 1) {
      let next
      do { next = Math.floor(Math.random() * q.length) } while (next === idx)
      await playAtIndex(next)
      return
    }
    if (idx < q.length - 1) {
      await playAtIndex(idx + 1)
    } else {
      setIsPlaying(false)
    }
    sendCommand('next')
  }

  // ── load track audio ─────────────────────────────────────────
  // seekToSec > 1: seek to that position once metadata is ready
  async function loadTrack(track, seekToSec = 0) {
    if (!audioRef.current) return
    setCurrentTrackId(track.id)
    setCurrentTime(0)
    setDuration(0)

    let src = ''
    try {
      const data = await apiFetch('/rest/getStreamInfo?id=' + track.id, {}, tokenRef.current)
      src = data.stream_url || ''
    } catch (e) {
      // 勿回退到本地缓存的 stream_url：库已重置或曲目已删时，旧 URL 只会造成 /resource 404
      if (e.status === 404) {
        clearLocalPlayerState()
        const q = queueRef.current.filter((t) => t.id !== track.id)
        const prevIdx = queueIndexRef.current
        const newIdx = q.length === 0 ? -1 : Math.min(prevIdx, q.length - 1)
        setQueue(q)
        queueRef.current = q
        setQueueIndex(newIdx)
        queueIndexRef.current = newIdx
        setCurrentTrackId(null)
      }
      return
    }

    if (src && !src.startsWith('http')) src = API_BASE + src

    const audio = audioRef.current
    // Remove any pending seek from a previous load
    if (audio._seekHandler) {
      audio.removeEventListener('loadedmetadata', audio._seekHandler)
      audio._seekHandler = null
    }
    if (seekToSec > 1) {
      const handler = () => {
        audio.currentTime = seekToSec
        audio.removeEventListener('loadedmetadata', handler)
        audio._seekHandler = null
      }
      audio._seekHandler = handler
      audio.addEventListener('loadedmetadata', handler)
    }

    audio.src = src
    audio.load()

    if (tokenRef.current) {
      apiFetch('/rest/scrobble', {
        method: 'POST',
        body: JSON.stringify({ track_id: track.id }),
      }, tokenRef.current).catch(() => {})
    }
  }

  // ── local play helpers ────────────────────────────────────────
  async function playAtIndex(idx) {
    const q = queueRef.current
    if (idx < 0 || idx >= q.length) return
    markActiveDevice()
    setQueueIndex(idx)
    queueIndexRef.current = idx
    await loadTrack(q[idx])
    audioRef.current.play().catch(() => {})
  }

  // ── apply state from server (initial load / accepted POST response) ────────
  const applyRemoteState = useCallback(async (state) => {
    const tracks = extractTracks(state.items)
    isActiveDeviceRef.current = state.active_device === DEVICE_ID
    setQueue(tracks)
    queueRef.current = tracks

    const idx = state.cursor ?? -1
    setQueueIndex(idx)
    queueIndexRef.current = idx

    setIsShuffle(state.shuffle ?? false)
    isShuffleRef.current = state.shuffle ?? false

    const rep = state.repeat_mode === 'one'
    setIsRepeat(rep)
    isRepeatRef.current = rep

    const track = tracks[idx]
    if (!track) {
      saveLocal(tracks, idx, state.position_sec || 0)
      return
    }

    const shouldControlPlayback = isActiveDeviceRef.current
    const targetPos = state.position_sec || 0
    const prevId = audioRef.current?._loadedTrackId

    if (shouldControlPlayback && track.id !== prevId) {
      // Load track and seek in one shot via loadedmetadata handler
      await loadTrack(track, targetPos)
      if (audioRef.current) audioRef.current._loadedTrackId = track.id
    } else if (shouldControlPlayback && Math.abs(audioRef.current.currentTime - targetPos) > 3) {
      // Same track, just seek
      audioRef.current.currentTime = targetPos
    }

    if (shouldControlPlayback && state.is_playing) {
      audioRef.current?.play().catch(() => {})
    } else if (shouldControlPlayback) {
      audioRef.current?.pause()
    }

    saveLocal(tracks, idx, state.position_sec || 0)
  }, [])

  // ── restore from localStorage（须带 token 校验，避免与已重置的 DB 脱节）───
  const restoreLocal = useCallback(async (tok) => {
    const saved = loadLocal()
    if (!saved || !saved.queue?.length || !tok) return
    const { queue: q, queueIndex: idx, position } = saved
    if (idx < 0 || idx >= q.length) {
      clearLocalPlayerState()
      return
    }
    const track = q[idx]
    if (!(await trackStillValid(track, tok))) {
      clearLocalPlayerState()
      return
    }
    setQueue(q)
    queueRef.current = q
    setQueueIndex(idx)
    queueIndexRef.current = idx
    await loadTrack(track, position || 0)
    if (audioRef.current) audioRef.current._loadedTrackId = track.id
    setCurrentTrackId(track.id)
  }, [])

  // ── fetch initial queue from server ──────────────────────────
  const fetchQueue = useCallback(async (tok) => {
    try {
      const state = await apiFetch('/rest/getPlayQueue', {}, tok)
      if (state.active_device === DEVICE_ID && state.items && state.items.length > 0) {
        await applyRemoteState(state)
      } else {
        await restoreLocal(tok)
      }
    } catch (_) {
      await restoreLocal(tok)
    }
  }, [applyRemoteState, restoreLocal])

  // ── token change: (re)connect ─────────────────────────────────
  useEffect(() => {
    if (token) {
      fetchQueue(token)
    }
  }, [token]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── public API ────────────────────────────────────────────────

  async function playTrack(track) {
    setQueue([track])
    queueRef.current = [track]
    setQueueIndex(0)
    queueIndexRef.current = 0
    markActiveDevice()
    await loadTrack(track)
    audioRef.current.play().catch(() => {})
    sendCommand('play_now', { track_ids: [track.id], start_index: 0 })
  }

  async function playFromContext(idx) {
    const cq = contextQueue
    if (idx < 0 || idx >= cq.length) return
    setQueue(cq)
    queueRef.current = cq
    setQueueIndex(idx)
    queueIndexRef.current = idx
    markActiveDevice()
    await loadTrack(cq[idx])
    audioRef.current.play().catch(() => {})
    sendCommand('play_now', {
      track_ids: cq.map(t => t.id),
      start_index: idx,
    })
  }

  const setContextQueue = useCallback((tracks) => {
    setContextQueueState(tracks)
  }, [])

  async function loadAndPlayTrack(id) {
    try {
      const track = await apiFetch('/rest/getSong?id=' + id, {}, token)
      playTrack(track)
    } catch (e) {
      console.error('loadAndPlayTrack error', e)
    }
  }

  function togglePlay() {
    if (!audioRef.current) return
    if (audioRef.current.paused) {
      markActiveDevice()
      audioRef.current.play().catch(() => {})
      sendCommand('play')
    } else {
      audioRef.current.pause()
      sendCommand('pause', { position_sec: audioRef.current.currentTime })
    }
  }

  function nextTrack() {
    const q   = queueRef.current
    const idx = queueIndexRef.current
    if (isShuffleRef.current && q.length > 1) {
      let next
      do { next = Math.floor(Math.random() * q.length) } while (next === idx)
      playAtIndex(next)
      return
    }
    if (idx < q.length - 1) playAtIndex(idx + 1)
    sendCommand('next')
  }

  function prevTrack() {
    const audio = audioRef.current
    if (!audio) return
    if (audio.currentTime > 3) {
      audio.currentTime = 0
      sendCommand('seek', { position_sec: 0 })
      return
    }
    const idx = queueIndexRef.current
    if (idx > 0) playAtIndex(idx - 1)
    sendCommand('prev')
  }

  function toggleShuffle() {
    const next = !isShuffle
    markActiveDevice()
    setIsShuffle(next)
    sendCommand('set_shuffle', { shuffle: next })
  }

  function toggleRepeat() {
    const next = !isRepeat
    markActiveDevice()
    setIsRepeat(next)
    sendCommand('set_repeat', { repeat_mode: next ? 'one' : 'none' })
  }

  function seekTo(pct) {
    if (!audioRef.current) return
    const d = (duration > 0 && isFinite(duration)) ? duration : 0
    if (!d) return
    const pos = pct * d
    markActiveDevice()
    audioRef.current.currentTime = pos
    sendCommand('seek', { position_sec: pos })
  }

  function setVolume(pct) {
    if (!audioRef.current) return
    audioRef.current.volume = Math.max(0, Math.min(1, pct))
  }

  // ── jump to arbitrary queue index ────────────────────────────
  async function jumpTo(idx) {
    await playAtIndex(idx)
    sendCommand('play_now', {
      track_ids: queueRef.current.map(t => t.id),
      start_index: idx,
    })
  }

  // ── queue management (play_next / append) ─────────────────────
  function playNext(track) {
    // Insert track right after current in local queue
    const q   = [...queueRef.current]
    const idx = queueIndexRef.current
    const insertAt = idx + 1
    q.splice(insertAt, 0, track)
    setQueue(q)
    queueRef.current = q
    sendCommand('play_next', { track_id: track.id })
  }

  function appendToQueue(track) {
    const q = [...queueRef.current, track]
    setQueue(q)
    queueRef.current = q
    sendCommand('append', { track_id: track.id })
  }

  const currentTrack = queue[queueIndex] || null

  return (
    <PlayerContext.Provider value={{
      queue, queueIndex, currentTrackId, currentTrack,
      isPlaying, isShuffle, isRepeat,
      contextQueue,
      audioRef,
      currentTime, duration,
      playTrack, playFromContext, setContextQueue,
      loadAndPlayTrack,
      togglePlay, nextTrack, prevTrack,
      toggleShuffle, toggleRepeat,
      seekTo, setVolume,
      playNext, appendToQueue, jumpTo,
    }}>
      {children}
    </PlayerContext.Provider>
  )
}

export function usePlayer() {
  return useContext(PlayerContext)
}
