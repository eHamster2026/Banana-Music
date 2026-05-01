import React, { createContext, useContext, useState, useEffect } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('am_token') || null)
  const [currentUser, setCurrentUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('am_user') || 'null')
    } catch {
      return null
    }
  })

  function login(tokenStr, userObj) {
    setToken(tokenStr)
    setCurrentUser(userObj)
    localStorage.setItem('am_token', tokenStr)
    localStorage.setItem('am_user', JSON.stringify(userObj))
  }

  function logout() {
    setToken(null)
    setCurrentUser(null)
    localStorage.removeItem('am_token')
    localStorage.removeItem('am_user')
  }

  return (
    <AuthContext.Provider value={{ token, currentUser, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
