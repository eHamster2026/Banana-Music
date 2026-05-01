import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

const UploadQueueContext = createContext(null)

const INITIAL_STATUS = {
  total: 0,
  waiting: 0,
  active: 0,
  completed: 0,
  failed: 0,
}

export function UploadQueueProvider({ children }) {
  const [status, setStatus] = useState(INITIAL_STATUS)
  const hideTimerRef = useRef(null)

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
  }, [])

  useEffect(() => () => clearHideTimer(), [clearHideTimer])

  useEffect(() => {
    clearHideTimer()

    const resolved = status.completed + status.failed
    const isFinished = status.total > 0 && status.waiting === 0 && status.active === 0 && resolved >= status.total
    if (!isFinished) return

    hideTimerRef.current = setTimeout(() => {
      setStatus(prev => {
        const done = prev.total > 0 && prev.waiting === 0 && prev.active === 0 && prev.completed + prev.failed >= prev.total
        return done ? INITIAL_STATUS : prev
      })
      hideTimerRef.current = null
    }, 2200)
  }, [status, clearHideTimer])

  const enqueueFiles = useCallback((count) => {
    if (count <= 0) return
    clearHideTimer()
    setStatus(prev => ({
      ...prev,
      total: prev.total + count,
      waiting: prev.waiting + count,
    }))
  }, [clearHideTimer])

  const startFile = useCallback(() => {
    clearHideTimer()
    setStatus(prev => ({
      ...prev,
      waiting: Math.max(0, prev.waiting - 1),
      active: prev.active + 1,
    }))
  }, [clearHideTimer])

  const finishFile = useCallback(({ ok = true } = {}) => {
    setStatus(prev => ({
      ...prev,
      active: Math.max(0, prev.active - 1),
      completed: prev.completed + (ok ? 1 : 0),
      failed: prev.failed + (ok ? 0 : 1),
    }))
  }, [])

  const value = useMemo(() => ({
    status,
    enqueueFiles,
    startFile,
    finishFile,
  }), [status, enqueueFiles, startFile, finishFile])

  return (
    <UploadQueueContext.Provider value={value}>
      {children}
    </UploadQueueContext.Provider>
  )
}

export function useUploadQueue() {
  const value = useContext(UploadQueueContext)
  if (!value) {
    throw new Error('useUploadQueue must be used within UploadQueueProvider')
  }
  return value
}
