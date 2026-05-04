import React from 'react'
import { AuthProvider } from './contexts/AuthContext'
import { PlayerProvider } from './contexts/PlayerContext'
import { NavProvider, useNav } from './contexts/NavContext'
import { ToastProvider } from './contexts/ToastContext'
import { ModalProvider } from './contexts/ModalContext'
import { UploadQueueProvider, useUploadQueue } from './contexts/UploadQueueContext'
import { useAuth } from './contexts/AuthContext'
import { useToast } from './contexts/ToastContext'
import { uploadLocalAudioFiles } from './localUpload.js'
import Sidebar from './components/Sidebar'
import MobileBottomNav from './components/MobileBottomNav'
import Topbar from './components/Topbar'
import Player from './components/Player'
import Toast from './components/Toast'
import UploadQueueStatus from './components/UploadQueueStatus'
import DropOverlay from './components/DropOverlay'
import QueuePanel from './components/QueuePanel'
import LoginModal from './components/modals/LoginModal'
import CreatePlaylistModal from './components/modals/CreatePlaylistModal'
import AddToPlaylistModal from './components/modals/AddToPlaylistModal'
import HomeView from './views/HomeView'
import LocalFilesView from './views/LocalFilesView'
import AlbumView from './views/AlbumView'
import PlaylistView from './views/PlaylistView'
import ArtistView from './views/ArtistView'
import LikedView from './views/LikedView'
import RecentlyAddedView from './views/RecentlyAddedView'
import AlbumLibraryView from './views/AlbumLibraryView'
import ArtistLibraryView from './views/ArtistLibraryView'
import AllPlaylistsView from './views/AllPlaylistsView'
import SearchView from './views/SearchView'
import AdminView from './views/AdminView'

function ContentRouter() {
  const { currentView, currentViewProps } = useNav()
  switch (currentView) {
    case 'home':  return <HomeView />
    case 'songs': return <LocalFilesView />
    case 'local': return <LocalFilesView />
    case 'album': return <AlbumView id={currentViewProps?.id} />
    case 'playlist': return <PlaylistView id={currentViewProps?.id} />
    case 'artist': return <ArtistView id={currentViewProps?.id} />
    case 'liked': return <LikedView />
    case 'recent': return <RecentlyAddedView />
    case 'albums': return <AlbumLibraryView />
    case 'artists': return <ArtistLibraryView />
    case 'playlists': return <AllPlaylistsView />
    case 'search': return <SearchView query={currentViewProps?.query} />
    case 'admin-tracks': return <AdminView tab="tracks" />
    case 'admin-users': return <AdminView tab="users" />
    case 'admin-plugins': return <AdminView tab="plugins" />
    default: return <HomeView />
  }
}

function LocalFileInputHandler() {
  const { token } = useAuth()
  const { showToast } = useToast()
  const uploadQueue = useUploadQueue()

  async function handleLocalFiles(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    await uploadLocalAudioFiles({
      files,
      token,
      showToast,
      progress: uploadQueue,
      onTrackResolved: async () => {
        window.dispatchEvent(new Event('localFilesUpdated'))
      },
    })
  }

  return (
    <input
      type="file"
      id="localFileInput"
      accept="audio/*,.ape,.wma"
      multiple
      style={{ display: 'none' }}
      onChange={handleLocalFiles}
    />
  )
}

function AppInner() {
  return (
    <>
      <div className="app">
        <Sidebar />
        <main className="main" id="main">
          <Topbar />
          <ContentRouter />
        </main>
      </div>
      <MobileBottomNav />
      <Player />
      <Toast />
      <UploadQueueStatus />
      <DropOverlay />
      <QueuePanel />
      <LoginModal />
      <CreatePlaylistModal />
      <AddToPlaylistModal />
      <LocalFileInputHandler />
    </>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <UploadQueueProvider>
          <ModalProvider>
            <NavProvider>
              <PlayerProvider>
                <AppInner />
              </PlayerProvider>
            </NavProvider>
          </ModalProvider>
        </UploadQueueProvider>
      </ToastProvider>
    </AuthProvider>
  )
}
