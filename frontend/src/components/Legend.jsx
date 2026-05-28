import React from 'react'

const FALLBACK_COLOR = '#6B7280'
const VIRTUAL_COLOR = '#0891B2'

export default function Legend({ categories }) {
  return (
    <div className="mt-4 p-3 bg-white rounded">
      <small className="text-muted d-block mb-2">Legend</small>
      <div className="d-flex flex-wrap gap-3">
        {categories.map(cat => (
          <div key={cat.name} className="d-flex align-items-center">
            <span
              className="d-inline-block me-1"
              style={{
                width: 12,
                height: 12,
                borderRadius: 2,
                backgroundColor: cat.color || FALLBACK_COLOR,
              }}
            />
            <small>{cat.name}</small>
          </div>
        ))}
        <div className="d-flex align-items-center">
          <span
            className="d-inline-block me-1"
            style={{
              width: 12,
              height: 12,
              borderRadius: 2,
              backgroundColor: VIRTUAL_COLOR,
            }}
          />
          <small>Virtual</small>
        </div>
      </div>
    </div>
  )
}
