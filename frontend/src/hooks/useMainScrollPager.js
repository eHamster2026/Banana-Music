import { useEffect } from 'react'

export default function useMainScrollPager({ hasMore, onLoadMore, threshold = 360 }) {
  useEffect(() => {
    const scroller = document.getElementById('main')
    if (!scroller || !hasMore) return

    let frame = 0
    const check = () => {
      frame = 0
      const remaining = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight
      if (remaining <= threshold) {
        onLoadMore()
      }
    }
    const scheduleCheck = () => {
      if (frame) return
      frame = window.requestAnimationFrame(check)
    }

    check()
    scroller.addEventListener('scroll', scheduleCheck, { passive: true })
    window.addEventListener('resize', scheduleCheck)
    return () => {
      if (frame) window.cancelAnimationFrame(frame)
      scroller.removeEventListener('scroll', scheduleCheck)
      window.removeEventListener('resize', scheduleCheck)
    }
  }, [hasMore, onLoadMore, threshold])
}
