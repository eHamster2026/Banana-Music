import React from 'react'
import { useToast } from '../contexts/ToastContext'

export default function Toast() {
  const { toasts } = useToast()

  return (
    <div className="toast-wrap">
      {toasts.map(t => (
        <div key={t.id} className="toast">{t.msg}</div>
      ))}
    </div>
  )
}
