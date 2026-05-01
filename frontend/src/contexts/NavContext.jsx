import React, { createContext, useCallback, useContext, useState } from 'react'
import { useTranslation } from 'react-i18next'

const NavContext = createContext(null)

function getViewTitleKey(viewName) {
  const map = {
    home: 'nav.home',
    songs: 'nav.mySongs',
    local: 'nav.home',
    album: 'nav.albums',
    playlist: 'nav.playlist',
    artist: 'nav.artists',
    liked: 'nav.liked',
    recent: 'nav.recent',
    albums: 'nav.albums',
    artists: 'nav.artists',
    playlists: 'nav.allPlaylists',
    search: 'nav.search',
    'admin-tracks': 'nav.adminTracks',
    'admin-users': 'nav.adminUsers',
    'admin-plugins': 'nav.adminPlugins',
  }
  return map[viewName]
}

function getViewTitle(viewName, t) {
  const key = getViewTitleKey(viewName)
  return key ? t(key) : viewName
}

function viewTitleState(viewName) {
  return { type: 'view', view: viewName }
}

function customTitleState(title) {
  return { type: 'custom', title }
}

function resolveTitleState(state, t) {
  if (state?.type === 'view') return getViewTitle(state.view, t)
  return state?.title || ''
}

export function NavProvider({ children }) {
  const { t } = useTranslation()
  const [currentView, setCurrentView] = useState('home')
  const [currentViewProps, setCurrentViewProps] = useState({})
  const [topbarTitleState, setTopbarTitleState] = useState(viewTitleState('home'))
  const [navStack, setNavStack] = useState([])
  const [navFwdStack, setNavFwdStack] = useState([])

  const topbarTitle = resolveTitleState(topbarTitleState, t)

  const setTopbarTitle = useCallback((title) => {
    setTopbarTitleState(customTitleState(title))
  }, [])

  function navigate(viewName, props = {}, title = null) {
    setNavStack(prev => [...prev, { view: currentView, props: currentViewProps, titleState: topbarTitleState }])
    setNavFwdStack([])
    setCurrentView(viewName)
    setCurrentViewProps(props)
    const defaultTitle = getViewTitle(viewName, t)
    setTopbarTitleState(title && title !== defaultTitle ? customTitleState(title) : viewTitleState(viewName))
  }

  function navBack() {
    if (navStack.length === 0) return
    const prev = navStack[navStack.length - 1]
    setNavFwdStack(f => [{ view: currentView, props: currentViewProps, titleState: topbarTitleState }, ...f])
    setNavStack(s => s.slice(0, -1))
    setCurrentView(prev.view)
    setCurrentViewProps(prev.props)
    setTopbarTitleState(prev.titleState || customTitleState(prev.title || ''))
  }

  function navForward() {
    if (navFwdStack.length === 0) return
    const next = navFwdStack[0]
    setNavStack(s => [...s, { view: currentView, props: currentViewProps, titleState: topbarTitleState }])
    setNavFwdStack(f => f.slice(1))
    setCurrentView(next.view)
    setCurrentViewProps(next.props)
    setTopbarTitleState(next.titleState || customTitleState(next.title || ''))
  }

  return (
    <NavContext.Provider value={{
      currentView, currentViewProps, topbarTitle, setTopbarTitle,
      navStack, navFwdStack,
      navigate, navBack, navForward
    }}>
      {children}
    </NavContext.Provider>
  )
}

export function useNav() {
  return useContext(NavContext)
}
