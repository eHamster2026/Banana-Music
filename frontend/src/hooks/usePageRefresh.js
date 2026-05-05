import { useEffect, useRef } from 'react'

const DEFAULT_INTERVAL_MS = 30_000

export default function usePageRefresh(callback, { intervalMs = DEFAULT_INTERVAL_MS, enabled = true } = {}) {
  const callbackRef = useRef(callback)
  const runningRef = useRef(false)

  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  useEffect(() => {
    if (!enabled) return undefined

    let cancelled = false
    const run = async () => {
      if (cancelled || runningRef.current || document.visibilityState !== 'visible') return
      runningRef.current = true
      try {
        await callbackRef.current?.()
      } catch {
        // Periodic refresh is best-effort; foreground actions surface their own errors.
      } finally {
        runningRef.current = false
      }
    }

    const timer = window.setInterval(run, intervalMs)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [enabled, intervalMs])
}
