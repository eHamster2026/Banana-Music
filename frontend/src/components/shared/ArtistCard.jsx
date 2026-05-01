import React from 'react'
import { useNav } from '../../contexts/NavContext'

export default function ArtistCard({ artist, onClick }) {
  const { navigate } = useNav()

  function handleClick() {
    if (onClick) { onClick(); return }
    navigate('artist', { id: artist.id }, artist.name)
  }

  return (
    <div className="artist-card" onClick={handleClick}>
      <div className={`artist-avatar ${artist.art_color || 'art-1'}`} />
      <div className="artist-name">{artist.name}</div>
    </div>
  )
}
