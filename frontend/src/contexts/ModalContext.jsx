import React, { createContext, useContext, useState } from 'react'

const ModalContext = createContext(null)

export function ModalProvider({ children }) {
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [showCreatePl, setShowCreatePl] = useState(false)
  const [showAddToPl, setShowAddToPl] = useState(false)
  const [addToPlTrackId, setAddToPlTrackId] = useState(null)

  function openAddToPlaylist(trackId) {
    setAddToPlTrackId(trackId)
    setShowAddToPl(true)
  }

  function closeAddToPl() {
    setShowAddToPl(false)
    setAddToPlTrackId(null)
  }

  return (
    <ModalContext.Provider value={{
      showLoginModal, setShowLoginModal,
      showCreatePl, setShowCreatePl,
      showAddToPl, addToPlTrackId,
      openAddToPlaylist, closeAddToPl,
    }}>
      {children}
    </ModalContext.Provider>
  )
}

export function useModal() {
  return useContext(ModalContext)
}
