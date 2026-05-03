import React, { useEffect, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { usePlayer } from '../contexts/PlayerContext'
import { apiFetch, fmtTime, formatTrackArtists, displayTrackTitle } from '../api.js'

// ── 小工具 ────────────────────────────────────────────────────
function Confirm({ msg, onOk, onCancel }) {
  const { t } = useTranslation()
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
    }}>
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 12, padding: '24px 28px', minWidth: 300, maxWidth: 420,
      }}>
        <div style={{ marginBottom: 20, fontSize: 14, color: 'var(--text)', lineHeight: 1.6 }}>{msg}</div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn-secondary" onClick={onCancel}>{t('admin.cancel')}</button>
          <button className="btn-primary" style={{ background: '#e74c3c' }} onClick={onOk}>{t('admin.confirm')}</button>
        </div>
      </div>
    </div>
  )
}

// ── 曲目编辑行内表单 ──────────────────────────────────────────
function TrackEditForm({ track, token, onSave, onCancel, onDeleteTrack }) {
  const { t } = useTranslation()
  const [form, setForm] = useState({
    title: track.title,
    artist_name: track.artist?.name || '',
    album_title: track.album?.title || '',
    track_number: track.track_number,
    duration_sec: track.duration_sec,
    lyrics: track.lyrics || '',
  })
  const [lookupLoading, setLookupLoading] = useState(false)
  const [candidates, setCandidates] = useState([])
  const { showToast } = useToast()

  async function handleSave() {
    try {
      const updated = await apiFetch(`/rest/x-banana/admin/tracks/${track.id}`, {
        method: 'PUT',
        body: JSON.stringify(form),
      }, token)
      onSave(updated)
    } catch (e) {
      showToast(t('admin.saveFailed') + e.message)
    }
  }

  async function handleLookupMetadata() {
    setLookupLoading(true)
    try {
      const results = await apiFetch('/rest/x-banana/plugins/metadata/lookup', {
        method: 'POST',
        body: JSON.stringify({ track_id: track.id }),
      }, token)
      setCandidates(results || [])
      if (!results || results.length === 0) {
        showToast(t('admin.noMetaCandidate'))
      } else {
        showToast(t('admin.metaCandidates', { count: results.length }))
      }
    } catch (e) {
      showToast(t('admin.metaFailed') + e.message)
    } finally {
      setLookupLoading(false)
    }
  }

  function applyCandidate(candidate) {
    setForm(f => ({
      ...f,
      title: candidate.title ?? f.title,
      artist_name: candidate.artist ?? f.artist_name,
      album_title: candidate.album ?? f.album_title,
      track_number: candidate.track_number ?? f.track_number,
      lyrics: candidate.lyrics ?? f.lyrics,
    }))
    showToast(t('admin.appliedCandidate', { plugin: candidate.plugin_id }))
  }

  const field = (key, label, type = 'text') => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
      <span style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{label}</span>
      <input
        type={type}
        value={form[key]}
        onChange={e => setForm(f => ({ ...f, [key]: type === 'number' ? Number(e.target.value) : e.target.value }))}
        style={{
          background: 'var(--hover)', border: '1px solid var(--border)', borderRadius: 6,
          padding: '6px 10px', color: 'var(--text)', fontSize: 13, outline: 'none',
        }}
      />
    </label>
  )

  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 8, padding: '16px', margin: '4px 0',
      display: 'flex', flexDirection: 'column', gap: 12,
    }}>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {field('title', t('admin.fieldTitle'))}
        {field('artist_name', t('admin.fieldArtist'))}
      </div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {field('album_title', t('admin.fieldAlbum'))}
        {field('track_number', t('admin.fieldTrackNum'), 'number')}
        {field('duration_sec', t('admin.fieldDuration'), 'number')}
      </div>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{t('admin.fieldLyrics')}</span>
        <textarea
          value={form.lyrics}
          onChange={e => setForm(f => ({ ...f, lyrics: e.target.value }))}
          rows={8}
          style={{
            background: 'var(--hover)', border: '1px solid var(--border)', borderRadius: 8,
            padding: '10px 12px', color: 'var(--text)', fontSize: 13, outline: 'none',
            resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5,
          }}
        />
      </label>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="btn-secondary"
            onClick={() => onDeleteTrack(track)}
            style={{ fontSize: 13, borderColor: 'rgba(231,76,60,0.4)', color: '#e74c3c' }}
          >
            {t('admin.deleteTrack')}
          </button>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button className="btn-secondary" onClick={handleLookupMetadata} disabled={lookupLoading} style={{ fontSize: 13 }}>
            {lookupLoading ? t('admin.looking') : t('admin.lookupBtn')}
          </button>
          <button className="btn-secondary" onClick={onCancel} style={{ fontSize: 13 }}>{t('admin.cancel')}</button>
          <button className="btn-primary" onClick={handleSave} style={{ fontSize: 13 }}>{t('admin.save', {defaultValue: t('common.save')})}</button>
        </div>
      </div>
      {candidates.length > 0 && (
        <div style={{
          marginTop: 4, paddingTop: 12, borderTop: '1px solid var(--border)',
          display: 'flex', flexDirection: 'column', gap: 10,
        }}>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{t('admin.candidatesSection')}</div>
          {candidates.map((candidate, idx) => (
            <div key={`${candidate.plugin_id}-${idx}`} style={{
              border: '1px solid var(--border)', borderRadius: 8, padding: '12px 14px',
              display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center',
            }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  {candidate.title || t('admin.unknownTitle')} · {candidate.artist || t('admin.unknownArtist')}
                </div>
                <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-secondary)' }}>
                  {candidate.album || t('admin.noAlbum')} · #{candidate.track_number || '—'} · {candidate.plugin_id} · {t('admin.confidence')} {Math.round((candidate.confidence || 0) * 100)}%
                </div>
                {(candidate.lyrics || candidate.cover_url) && (
                  <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-secondary)' }}>
                    {candidate.lyrics ? t('admin.hasLyrics') : t('admin.noLyrics')} · {candidate.cover_url ? t('admin.hasCover') : t('admin.noCover')}
                  </div>
                )}
              </div>
              <button className="btn-secondary" onClick={() => applyCandidate(candidate)} style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                {t('admin.applyCandidate')}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── 曲目管理 Tab ──────────────────────────────────────────────
function TracksTab({ token }) {
  const { t } = useTranslation()
  const [tracks, setTracks] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [q, setQ] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [confirm, setConfirm] = useState(null)  // { msg, onOk }
  const { showToast } = useToast()
  const { currentTrackId, playFromContext, setContextQueue } = usePlayer()

  function playAll(startIdx = 0) {
    setContextQueue(tracks)
    playFromContext(startIdx)
  }
  const PAGE = 50

  const load = useCallback(async (pageNum = 0, query = q) => {
    try {
      const data = await apiFetch(
        `/rest/x-banana/admin/tracks?skip=${pageNum * PAGE}&limit=${PAGE}${query ? `&q=${encodeURIComponent(query)}` : ''}`,
        {}, token
      )
      setTracks(data.items)
      setTotal(data.total)
      setPage(pageNum)
    } catch (e) {
      showToast(t('admin.loadFailed') + e.message)
    }
  }, [token, q, t, showToast])

  useEffect(() => { load(0) }, [token])

  function handleSearch(e) {
    e.preventDefault()
    load(0, q)
  }

  function handleSaved(updated) {
    setTracks(ts => ts.map(t => t.id === updated.id ? updated : t))
    setEditingId(null)
    showToast(t('common.save'))
  }

  function askDeleteTrack(track) {
    setConfirm({
      msg: t('admin.deleteTrackConfirm', { title: displayTrackTitle(track) }),
      onOk: async () => {
        setConfirm(null)
        try {
          await apiFetch(`/rest/x-banana/admin/tracks/${track.id}`, { method: 'DELETE' }, token)
          setTracks(ts => ts.filter(t => t.id !== track.id))
          setTotal(n => n - 1)
          showToast(t('admin.trackDeleted'))
        } catch (e) { showToast(t('admin.deleteFailed') + e.message) }
      },
    })
  }

  const totalPages = Math.ceil(total / PAGE)
  const trackHeaders = [
    { label: '', width: 42 },
    { label: t('admin.colId'), width: 64 },
    { label: t('admin.colTitle'), width: 230 },
    { label: t('admin.colArtist'), width: 180 },
    { label: t('admin.colAlbum'), width: 200 },
    { label: t('admin.colDuration'), width: 86 },
    { label: t('admin.colFile'), width: 88 },
    { label: t('admin.colActions'), width: 100 },
  ]
  const ellipsisCell = {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    minWidth: 0,
  }

  return (
    <div>
      {confirm && <Confirm msg={confirm.msg} onOk={confirm.onOk} onCancel={() => setConfirm(null)} />}

      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
        <form onSubmit={handleSearch} style={{ display: 'flex', gap: 8, flex: 1 }}>
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder={t('admin.trackSearch')}
            style={{
              flex: 1, background: 'var(--hover)', border: '1px solid var(--border)',
              borderRadius: 8, padding: '8px 14px', color: 'var(--text)', fontSize: 13, outline: 'none',
            }}
          />
          <button type="submit" className="btn-secondary" style={{ fontSize: 13 }}>{t('admin.trackSearchBtn')}</button>
        </form>
        {tracks.length > 0 && (
          <button className="btn-primary" onClick={() => playAll(0)} style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
            {t('admin.playAll')}
          </button>
        )}
        <span style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{t('admin.totalTracks', { total })}</span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', minWidth: 990, tableLayout: 'fixed', borderCollapse: 'collapse', fontSize: 13 }}>
          <colgroup>
            {trackHeaders.map((h, idx) => (
              <col key={`${h.label}-${idx}`} style={{ width: h.width }} />
            ))}
          </colgroup>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
              {trackHeaders.map((h, idx) => (
                <th key={`${h.label}-${idx}`} style={{ padding: '8px 10px', textAlign: 'left', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tracks.map(track => {
              const artistText = formatTrackArtists(track) || '—'
              const albumText = track.album?.title || '—'
              const titleText = displayTrackTitle(track)
              return (
              <React.Fragment key={track.id}>
                <tr style={{ borderBottom: '1px solid var(--border)', transition: 'background 0.1s' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--hover)'}
                  onMouseLeave={e => e.currentTarget.style.background = ''}>
                  <td style={{ padding: '10px 6px 10px 10px', width: 32 }}>
                    <button
                      onClick={() => playAll(tracks.indexOf(track))}
                      disabled={!track.stream_url}
                      title={track.stream_url ? t('admin.playTrack') : t('admin.noFile')}
                      style={{
                        background: 'none', border: 'none', cursor: track.stream_url ? 'pointer' : 'default',
                        color: currentTrackId === track.id ? 'var(--accent)' : 'var(--text-secondary)',
                        fontSize: 14, padding: 0, opacity: track.stream_url ? 1 : 0.3,
                        width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                      {currentTrackId === track.id ? '♫' : '▶'}
                    </button>
                  </td>
                  <td style={{ padding: '10px 10px', color: 'var(--text-secondary)', ...ellipsisCell }}>{track.id}</td>
                  <td
                    title={titleText}
                    style={{ padding: '10px 10px', color: currentTrackId === track.id ? 'var(--accent)' : 'var(--text)', ...ellipsisCell }}
                  >
                    {titleText}
                  </td>
                  <td
                    title={artistText}
                    style={{ padding: '10px 10px', color: 'var(--text-secondary)', ...ellipsisCell }}
                  >
                    {artistText}
                  </td>
                  <td
                    title={albumText}
                    style={{ padding: '10px 10px', color: 'var(--text-secondary)', ...ellipsisCell }}
                  >
                    {albumText}
                  </td>
                  <td style={{ padding: '10px 10px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{fmtTime(track.duration_sec)}</td>
                  <td style={{ padding: '10px 10px', overflow: 'hidden' }}>
                    <span style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 10,
                      background: track.stream_url ? 'rgba(39,174,96,0.2)' : 'rgba(231,76,60,0.2)',
                      color: track.stream_url ? '#27ae60' : '#e74c3c',
                      display: 'inline-block', maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {track.stream_url ? t('admin.hasFile') : t('admin.noFile')}
                    </span>
                  </td>
                  <td style={{ padding: '10px 10px', whiteSpace: 'nowrap' }}>
                    <button
                      onClick={() => setEditingId(editingId === track.id ? null : track.id)}
                      style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', color: 'var(--text)', fontSize: 12 }}>
                      {t('admin.edit', {defaultValue: t('common.edit')})}
                    </button>
                  </td>
                </tr>
                {editingId === track.id && (
                  <tr>
                    <td colSpan={8} style={{ padding: '0 10px 8px' }}>
                      <TrackEditForm
                        track={track}
                        token={token}
                        onSave={handleSaved}
                        onCancel={() => setEditingId(null)}
                        onDeleteTrack={askDeleteTrack}
                      />
                    </td>
                  </tr>
                )}
              </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 16 }}>
          <button className="btn-secondary" disabled={page === 0} onClick={() => load(page - 1)} style={{ fontSize: 13 }}>{t('admin.prevPage')}</button>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: '32px' }}>{page + 1} / {totalPages}</span>
          <button className="btn-secondary" disabled={page >= totalPages - 1} onClick={() => load(page + 1)} style={{ fontSize: 13 }}>{t('admin.nextPage')}</button>
        </div>
      )}
    </div>
  )
}

const USER_FORM_INPUT_STYLE = {
  background: 'var(--hover)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '7px 10px', color: 'var(--text)', fontSize: 13, outline: 'none', width: '100%', boxSizing: 'border-box',
}

const EMPTY_USER_FORM = { username: '', email: '', password: '', is_admin: false }

// ── 用户管理 Tab ──────────────────────────────────────────────
function UsersTab({ token, currentUser }) {
  const { t } = useTranslation()
  const [users, setUsers] = useState([])
  const [confirm, setConfirm] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_USER_FORM)
  const [creating, setCreating] = useState(false)
  const { showToast } = useToast()

  useEffect(() => {
    apiFetch('/rest/x-banana/admin/users', {}, token)
      .then(setUsers)
      .catch(e => showToast(t('admin.loadUsersFailed') + e.message))
  }, [token, t, showToast])

  async function handleCreate(e) {
    e.preventDefault()
    if (!form.username.trim() || !form.email.trim() || !form.password) {
      showToast(t('admin.fillRequired'))
      return
    }
    setCreating(true)
    try {
      const user = await apiFetch('/rest/x-banana/admin/users', {
        method: 'POST',
        body: JSON.stringify(form),
      }, token)
      setUsers(us => [...us, user])
      setForm(EMPTY_USER_FORM)
      setShowCreate(false)
      showToast(t('admin.userCreated', { name: user.username }))
    } catch (e) {
      showToast(t('admin.createUserFailed') + e.message)
    } finally {
      setCreating(false)
    }
  }

  async function toggleAdmin(user) {
    try {
      const updated = await apiFetch(`/rest/x-banana/admin/users/${user.id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_admin: !user.is_admin }),
      }, token)
      setUsers(us => us.map(u => u.id === updated.id ? updated : u))
      showToast(updated.is_admin ? t('admin.grantedAdmin', { name: updated.username }) : t('admin.revokedAdmin', { name: updated.username }))
    } catch (e) { showToast(t('admin.roleFailed') + e.message) }
  }

  function askDelete(user) {
    setConfirm({
      msg: t('admin.deleteUserConfirm', { name: user.username }),
      onOk: async () => {
        setConfirm(null)
        try {
          await apiFetch(`/rest/x-banana/admin/users/${user.id}`, { method: 'DELETE' }, token)
          setUsers(us => us.filter(u => u.id !== user.id))
          showToast(t('admin.userDeleted'))
        } catch (e) { showToast(t('admin.deleteFailed') + e.message) }
      },
    })
  }

  return (
    <div>
      {confirm && <Confirm msg={confirm.msg} onOk={confirm.onOk} onCancel={() => setConfirm(null)} />}

      <div style={{ marginBottom: 14 }}>
        <button
          className="btn-primary"
          onClick={() => setShowCreate(v => !v)}
          style={{ fontSize: 13 }}
        >
          {showCreate ? t('admin.cancel') : t('admin.newUserBtn')}
        </button>
      </div>

      {showCreate && (
        <form onSubmit={handleCreate} style={{
          background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10,
          padding: '18px 20px', marginBottom: 18, display: 'flex', flexDirection: 'column', gap: 14,
        }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{t('admin.newUserTitle')}</div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <label style={{ flex: 1, minWidth: 140, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{t('admin.usernamLabel')}</span>
              <input style={USER_FORM_INPUT_STYLE} value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))} placeholder="username" />
            </label>
            <label style={{ flex: 1, minWidth: 180, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{t('admin.emailLabel')}</span>
              <input style={USER_FORM_INPUT_STYLE} type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} placeholder="user@example.com" />
            </label>
            <label style={{ flex: 1, minWidth: 140, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{t('admin.passwordLabel')}</span>
              <input style={USER_FORM_INPUT_STYLE} type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} placeholder="••••••" />
            </label>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
              <input type="checkbox" checked={form.is_admin} onChange={e => setForm(f => ({ ...f, is_admin: e.target.checked }))} />
              {t('admin.isAdmin')}
            </label>
            <button type="submit" className="btn-primary" disabled={creating} style={{ fontSize: 13 }}>
              {creating ? t('admin.creating') : t('admin.createBtn')}
            </button>
          </div>
        </form>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
            {[t('admin.colIdUser'), t('admin.colUsername'), t('admin.colEmail'), t('admin.colAdmin'), t('admin.colCreated'), t('admin.colActionsUser')].map(h => (
              <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontWeight: 500 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {users.map(user => (
            <tr key={user.id}
              style={{ borderBottom: '1px solid var(--border)' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--hover)'}
              onMouseLeave={e => e.currentTarget.style.background = ''}>
              <td style={{ padding: '10px 10px', color: 'var(--text-secondary)' }}>{user.id}</td>
              <td style={{ padding: '10px 10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{
                    width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                    background: `var(--${user.avatar_color || 'art-1'})`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 12, fontWeight: 600, color: '#fff',
                  }}>
                    {user.username[0].toUpperCase()}
                  </div>
                  {user.username}
                  {user.id === currentUser?.id && (
                    <span style={{ fontSize: 10, color: 'var(--accent)', marginLeft: 2 }}>{t('admin.youLabel')}</span>
                  )}
                </div>
              </td>
              <td style={{ padding: '10px 10px', color: 'var(--text-secondary)' }}>{user.email}</td>
              <td style={{ padding: '10px 10px' }}>
                <span style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 10,
                  background: user.is_admin ? 'rgba(var(--accent-rgb,82,130,255),0.2)' : 'var(--hover)',
                  color: user.is_admin ? 'var(--accent)' : 'var(--text-secondary)',
                }}>
                  {user.is_admin ? t('admin.roleAdmin') : t('admin.roleUser')}
                </span>
              </td>
              <td style={{ padding: '10px 10px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                {user.created_at ? new Date(user.created_at * 1000).toLocaleDateString('zh-CN') : '—'}
              </td>
              <td style={{ padding: '10px 10px', whiteSpace: 'nowrap' }}>
                <button
                  onClick={() => toggleAdmin(user)}
                  disabled={user.id === currentUser?.id}
                  style={{
                    background: 'none', border: '1px solid var(--border)', borderRadius: 6,
                    padding: '4px 10px', cursor: user.id === currentUser?.id ? 'not-allowed' : 'pointer',
                    color: 'var(--text)', fontSize: 12, marginRight: 6,
                    opacity: user.id === currentUser?.id ? 0.4 : 1,
                  }}>
                  {user.is_admin ? t('admin.revokeAdmin') : t('admin.makeAdmin')}
                </button>
                <button
                  onClick={() => askDelete(user)}
                  disabled={user.id === currentUser?.id}
                  style={{
                    background: 'rgba(231,76,60,0.15)', border: 'none', borderRadius: 6,
                    padding: '4px 10px', cursor: user.id === currentUser?.id ? 'not-allowed' : 'pointer',
                    color: '#e74c3c', fontSize: 12,
                    opacity: user.id === currentUser?.id ? 0.4 : 1,
                  }}>
                  {t('admin.deleteUser')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const PLUGIN_INPUT_STYLE = {
  background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '7px 10px', color: 'var(--text)', fontSize: 13, outline: 'none', width: '100%', boxSizing: 'border-box',
}

function PluginConfigField({ fieldKey, spec, value, onChange }) {
  const type = spec.type || 'string'
  const label = spec.title || fieldKey

  if (spec.enum?.length) {
    return (
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{label}</span>
        <select
          className="plugin-config-select"
          value={value ?? spec.default ?? ''}
          onChange={e => onChange(fieldKey, e.target.value)}
          style={PLUGIN_INPUT_STYLE}
        >
          {spec.enum.map(option => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
        {spec.description && <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{spec.description}</span>}
      </label>
    )
  }

  if (type === 'boolean') {
    return (
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={e => onChange(fieldKey, e.target.checked)}
        />
        <span>{label}</span>
      </label>
    )
  }

  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{label}</span>
      <input
        type={type === 'number' ? 'number' : 'text'}
        value={value ?? spec.default ?? ''}
        onChange={e => {
          const nextValue = type === 'number'
            ? (e.target.value === '' ? '' : Number(e.target.value))
            : e.target.value
          onChange(fieldKey, nextValue)
        }}
        style={PLUGIN_INPUT_STYLE}
      />
      {spec.description && <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{spec.description}</span>}
    </label>
  )
}

function PluginsTab({ token }) {
  const { t } = useTranslation()
  const [plugins, setPlugins] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [form, setForm] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [acting, setActing] = useState(false)
  const { showToast } = useToast()

  const mergePluginSummary = useCallback((updated) => {
    setPlugins(list => list.map(item => item.id === updated.id ? {
      ...item,
      enabled: updated.enabled,
      loaded: updated.loaded,
      error: updated.error,
      capabilities: updated.capabilities,
      name: updated.name,
      version: updated.version,
    } : item))
  }, [])

  const loadDetail = useCallback(async (pluginId) => {
    const data = await apiFetch(`/rest/x-banana/plugins/${pluginId}`, {}, token)
    setSelectedId(pluginId)
    setDetail(data)
    setForm(data.config || {})
    mergePluginSummary(data)
    return data
  }, [token, mergePluginSummary])

  const loadPlugins = useCallback(async (preferredId = null) => {
    setLoading(true)
    try {
      const data = await apiFetch('/rest/x-banana/plugins', {}, token)
      setPlugins(data)
      const nextId = preferredId || selectedId || data[0]?.id || null
      if (nextId) {
        await loadDetail(nextId)
      } else {
        setSelectedId(null)
        setDetail(null)
        setForm({})
      }
    } catch (e) {
      showToast(t('admin.pluginLoadFailed') + e.message)
    } finally {
      setLoading(false)
    }
  }, [token, selectedId, loadDetail])

  useEffect(() => { loadPlugins() }, [token])

  function updateField(fieldKey, value) {
    setForm(prev => ({ ...prev, [fieldKey]: value }))
  }

  async function saveConfig(e) {
    e.preventDefault()
    if (!selectedId) return
    setSaving(true)
    try {
      const updated = await apiFetch(`/rest/x-banana/plugins/${selectedId}/config`, {
        method: 'PUT',
        body: JSON.stringify({ config: form }),
      }, token)
      setDetail(updated)
      setForm(updated.config || {})
      mergePluginSummary(updated)
      showToast(t('admin.pluginSaved', { name: updated.name }))
    } catch (e) {
      showToast(t('admin.pluginSaveFailed') + e.message)
    } finally {
      setSaving(false)
    }
  }

  async function runAction(action) {
    if (!selectedId) return
    setActing(true)
    try {
      const updated = await apiFetch(`/rest/x-banana/plugins/${selectedId}/${action}`, {
        method: 'POST',
      }, token)
      setDetail(updated)
      setForm(updated.config || {})
      mergePluginSummary(updated)
      const actionLabel = action === 'reload'
        ? t('admin.pluginReloaded')
        : action === 'enable'
          ? t('admin.pluginEnabled')
          : t('admin.pluginDisabled')
      showToast(t('admin.pluginToggled', { action: actionLabel, name: updated.name }))
    } catch (e) {
      showToast(t('admin.pluginToggleFailed') + e.message)
    } finally {
      setActing(false)
    }
  }

  if (loading) {
    return <div className="loading-wrap"><div className="spinner" /></div>
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '320px minmax(0, 1fr)', gap: 18 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {plugins.map(plugin => (
          <button
            key={plugin.id}
            onClick={() => loadDetail(plugin.id)}
            style={{
              textAlign: 'left',
              background: plugin.id === selectedId ? 'var(--surface)' : 'var(--card)',
              border: plugin.id === selectedId ? '1px solid var(--accent)' : '1px solid var(--border)',
              borderRadius: 10,
              padding: '14px 16px',
              cursor: 'pointer',
              color: 'var(--text)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{plugin.name}</div>
              <span style={{
                fontSize: 11, padding: '2px 8px', borderRadius: 999,
                background: plugin.enabled ? 'rgba(39,174,96,0.18)' : 'rgba(231,76,60,0.16)',
                color: plugin.enabled ? '#27ae60' : '#e74c3c',
              }}>
                {plugin.enabled ? t('admin.pluginStatusEnabled') : t('admin.pluginStatusDisabled')}
              </span>
            </div>
            <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
              {plugin.id} · v{plugin.version}
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
              {plugin.capabilities.map(cap => (
                <span key={cap} style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 999,
                  background: 'var(--hover)', color: 'var(--text-secondary)',
                }}>
                  {cap}
                </span>
              ))}
            </div>
            {!plugin.loaded && plugin.error && (
              <div style={{ marginTop: 10, fontSize: 12, color: '#e67e22' }}>
                {t('admin.pluginLoadError')}{plugin.error}
              </div>
            )}
          </button>
        ))}
      </div>

      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 12,
        padding: '20px 22px',
      }}>
        {!detail ? (
          <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{t('admin.noPlugins')}</div>
        ) : (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', marginBottom: 18 }}>
              <div>
                <h2 style={{ margin: 0, fontSize: 20 }}>{detail.name}</h2>
                <div style={{ marginTop: 6, color: 'var(--text-secondary)', fontSize: 13 }}>
                  {detail.id} · v{detail.version}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                <button className="btn-secondary" disabled={acting} onClick={() => runAction('reload')} style={{ fontSize: 13 }}>
                  {t('admin.pluginReload')}
                </button>
                {detail.enabled ? (
                  <button className="btn-secondary" disabled={acting} onClick={() => runAction('disable')} style={{ fontSize: 13 }}>
                    {t('admin.pluginDisableBtn')}
                  </button>
                ) : (
                  <button className="btn-primary" disabled={acting} onClick={() => runAction('enable')} style={{ fontSize: 13 }}>
                    {t('admin.pluginEnableBtn')}
                  </button>
                )}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
              <span style={{
                fontSize: 11, padding: '2px 8px', borderRadius: 999,
                background: detail.enabled ? 'rgba(39,174,96,0.18)' : 'rgba(231,76,60,0.16)',
                color: detail.enabled ? '#27ae60' : '#e74c3c',
              }}>
                {detail.enabled ? t('admin.pluginStatusEnabled') : t('admin.pluginStatusDisabled')}
              </span>
              <span style={{
                fontSize: 11, padding: '2px 8px', borderRadius: 999,
                background: detail.loaded ? 'rgba(82,130,255,0.16)' : 'rgba(230,126,34,0.16)',
                color: detail.loaded ? 'var(--accent)' : '#e67e22',
              }}>
                {detail.loaded ? t('admin.pluginStatusLoaded') : t('admin.pluginStatusNotLoaded')}
              </span>
              {detail.capabilities.map(cap => (
                <span key={cap} style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 999,
                  background: 'var(--hover)', color: 'var(--text-secondary)',
                }}>
                  {cap}
                </span>
              ))}
            </div>

            {detail.error && (
              <div style={{
                marginBottom: 16, padding: '10px 12px', borderRadius: 8,
                background: 'rgba(230,126,34,0.12)', color: '#e67e22', fontSize: 13,
              }}>
                {t('admin.pluginLoadErrorCurrent')}{detail.error}
              </div>
            )}

            <form onSubmit={saveConfig} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {Object.entries(detail.config_schema?.properties || {}).length === 0 ? (
                <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{t('admin.pluginNoConfig')}</div>
              ) : (
                Object.entries(detail.config_schema.properties).map(([fieldKey, spec]) => (
                  <PluginConfigField
                    key={fieldKey}
                    fieldKey={fieldKey}
                    spec={spec}
                    value={form[fieldKey]}
                    onChange={updateField}
                  />
                ))
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
                <button type="submit" className="btn-primary" disabled={saving} style={{ fontSize: 13 }}>
                  {saving ? t('common.saving') : t('admin.pluginSaveBtn')}
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  )
}

// ── 主视图 ────────────────────────────────────────────────────
export default function AdminView({ tab = 'tracks' }) {
  const { t } = useTranslation()
  const { token, currentUser } = useAuth()

  const titles = {
    tracks: t('admin.pageTracksTitle'),
    users: t('admin.pageUsersTitle'),
    plugins: t('admin.pagePluginsTitle'),
  }
  const subtitles = {
    tracks: t('admin.pageTracksSubtitle'),
    users: t('admin.pageUsersSubtitle'),
    plugins: t('admin.pagePluginsSubtitle'),
  }

  return (
    <div style={{ padding: '24px 28px 40px' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, marginBottom: 4 }}>{titles[tab]}</h1>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>{subtitles[tab]}</p>
      </div>

      {tab === 'tracks' && <TracksTab token={token} />}
      {tab === 'users' && <UsersTab token={token} currentUser={currentUser} />}
      {tab === 'plugins' && <PluginsTab token={token} />}
    </div>
  )
}
