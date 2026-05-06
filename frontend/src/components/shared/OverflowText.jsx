import React from 'react'

export default function OverflowText({ as: Tag = 'div', className = '', children, title, ...props }) {
  const text = title ?? (typeof children === 'string' ? children : undefined)
  return (
    <Tag className={`overflow-text ${className}`.trim()} title={text} {...props}>
      {children}
    </Tag>
  )
}
