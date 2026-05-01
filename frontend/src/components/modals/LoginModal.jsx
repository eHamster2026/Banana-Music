import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useModal } from '../../contexts/ModalContext'
import { useAuth } from '../../contexts/AuthContext'
import { useToast } from '../../contexts/ToastContext'
import { apiFetch } from '../../api.js'

export default function LoginModal() {
  const { t } = useTranslation()
  const { showLoginModal, setShowLoginModal } = useModal()
  const { login } = useAuth()
  const { showToast } = useToast()
  const [tab, setTab] = useState('login')
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [regForm, setRegForm] = useState({ username: '', email: '', password: '' })
  const [loginError, setLoginError] = useState('')
  const [regError, setRegError] = useState('')
  const [loading, setLoading] = useState(false)

  if (!showLoginModal) return null

  function close() {
    setShowLoginModal(false)
    setLoginError('')
    setRegError('')
  }

  function fillDemo() {
    setLoginForm({ username: 'demo', password: 'demo123' })
  }

  async function doLogin() {
    setLoginError('')
    setLoading(true)
    try {
      const data = await apiFetch('/rest/x-banana/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: loginForm.username, password: loginForm.password }),
      })
      login(data.access_token, data.user || { username: loginForm.username })
      showToast(t('login.welcomeBack', { name: loginForm.username }))
      close()
    } catch (e) {
      setLoginError(e.message || t('login.failLogin'))
    } finally {
      setLoading(false)
    }
  }

  async function doRegister() {
    setRegError('')
    setLoading(true)
    try {
      const data = await apiFetch('/rest/x-banana/auth/register', {
        method: 'POST',
        body: JSON.stringify(regForm),
      })
      login(data.access_token, data.user || { username: regForm.username })
      showToast(t('login.registerOk', { name: regForm.username }))
      close()
    } catch (e) {
      setRegError(e.message || t('login.failRegister'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && close()}>
      <div className="modal">
        <button className="modal-close" onClick={close}>×</button>
        <div className="modal-logo">
          <span style={{ fontSize: 48, lineHeight: 1 }}>🎵</span>
        </div>
        <div className="modal-title">{t('login.title')}</div>
        <div className="modal-sub">{t('login.subtitle')}</div>
        <div className="modal-tabs">
          <div className={`modal-tab${tab === 'login' ? ' active' : ''}`} onClick={() => setTab('login')}>{t('login.tabLogin')}</div>
          <div className={`modal-tab${tab === 'register' ? ' active' : ''}`} onClick={() => setTab('register')}>{t('login.tabRegister')}</div>
        </div>

        {tab === 'login' && (
          <div>
            <div className="modal-field">
              <label>{t('login.username')}</label>
              <input
                type="text"
                placeholder={t('login.placeholderUsername')}
                autoComplete="username"
                value={loginForm.username}
                onChange={e => setLoginForm(f => ({ ...f, username: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && doLogin()}
              />
            </div>
            <div className="modal-field">
              <label>{t('login.password')}</label>
              <input
                type="password"
                placeholder={t('login.placeholderPassword')}
                autoComplete="current-password"
                value={loginForm.password}
                onChange={e => setLoginForm(f => ({ ...f, password: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && doLogin()}
              />
            </div>
            <div className="modal-error">{loginError}</div>
            <button className="modal-submit" disabled={loading} onClick={doLogin}>
              {loading ? t('login.loggingIn') : t('login.login')}
            </button>
            <div className="modal-demo">{t('login.demo')}<a onClick={fillDemo}>{t('login.demoLink')}</a></div>
          </div>
        )}

        {tab === 'register' && (
          <div>
            <div className="modal-field">
              <label>{t('login.username')}</label>
              <input
                type="text"
                placeholder={t('login.placeholderPickUsername')}
                autoComplete="username"
                value={regForm.username}
                onChange={e => setRegForm(f => ({ ...f, username: e.target.value }))}
              />
            </div>
            <div className="modal-field">
              <label>{t('login.email')}</label>
              <input
                type="email"
                placeholder="your@email.com"
                autoComplete="email"
                value={regForm.email}
                onChange={e => setRegForm(f => ({ ...f, email: e.target.value }))}
              />
            </div>
            <div className="modal-field">
              <label>{t('login.password')}</label>
              <input
                type="password"
                placeholder={t('login.placeholderPasswordMin')}
                autoComplete="new-password"
                value={regForm.password}
                onChange={e => setRegForm(f => ({ ...f, password: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && doRegister()}
              />
            </div>
            <div className="modal-error">{regError}</div>
            <button className="modal-submit" disabled={loading} onClick={doRegister}>
              {loading ? t('login.registering') : t('login.register')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
