import React from 'react'

const FALLBACK_COLOR = '#6B7280'

export default function FilterChips({ categories, selected, onToggle }) {
  return (
    <div className="mb-3 d-flex flex-wrap gap-2">
      {categories.map(cat => {
        const isSelected = selected.includes(cat.name)
        const color = cat.color || FALLBACK_COLOR
        return (
          <button
            key={cat.name}
            className={`btn btn-sm ${isSelected ? '' : 'btn-outline-secondary'}`}
            style={isSelected ? { backgroundColor: color, borderColor: color, color: 'white' } : {}}
            onClick={() => onToggle(cat.name)}
          >
            {cat.name}
          </button>
        )
      })}
    </div>
  )
}
