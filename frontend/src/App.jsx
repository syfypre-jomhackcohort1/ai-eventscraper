import React, { useState, useEffect, useRef } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin from '@fullcalendar/interaction'
import EventModal from './components/EventModal'
import FilterChips from './components/FilterChips'
import Legend from './components/Legend'

// Fallback used only when an event has a category not present in the API
// (e.g. the legacy "Tech" bucket assigned by some scrapers).
const FALLBACK_COLOR = '#6B7280'

export default function App() {
  const [events, setEvents] = useState([])
  const [categories, setCategories] = useState([])
  const [selectedCategories, setSelectedCategories] = useState([])
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [hoveredEvent, setHoveredEvent] = useState(null)
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 })
  const [currentMonth, setCurrentMonth] = useState(new Date().toISOString().slice(0, 7))
  const [refreshKey, setRefreshKey] = useState(0)
  const [loading, setLoading] = useState(true)
  const calendarRef = useRef(null)

  // Fetch categories once on mount
  useEffect(() => {
    const loadCategories = async () => {
      try {
        const res = await fetch('/api/categories')
        const data = await res.json()
        setCategories(data)
        setSelectedCategories(data.map(c => c.name))
      } catch (err) {
        console.error('Failed to fetch categories:', err)
      }
    }
    loadCategories()
  }, [])

  // Fetch events when month or selected categories change
  useEffect(() => {
    if (selectedCategories.length === 0 && categories.length === 0) return
    const loadEvents = async () => {
      setLoading(true)
      try {
        const params = new URLSearchParams({ month: currentMonth })
        if (selectedCategories.length > 0 && selectedCategories.length < categories.length) {
          params.append('category', selectedCategories.join(','))
        }
        const res = await fetch(`/api/events?${params}`)
        const data = await res.json()
        setEvents(data.map(formatEvent))
      } catch (err) {
        console.error('Failed to fetch events:', err)
      } finally {
        setLoading(false)
      }
    }
    loadEvents()
  }, [currentMonth, selectedCategories.join(','), refreshKey])

  // Sync FullCalendar view with currentMonth
  useEffect(() => {
    if (calendarRef.current) {
      const calendarApi = calendarRef.current.getApi()
      const [y, m] = currentMonth.split('-').map(Number)
      calendarApi.gotoDate(new Date(y, m - 1, 1))
    }
  }, [currentMonth])

  const formatEvent = (event) => {
    const category = event.categories?.[0] || 'Other'
    const categoryDef = categories.find(c => c.name === category)
    const color = categoryDef?.color || FALLBACK_COLOR

    // FullCalendar's `end` is exclusive. Two cases:
    //  - All-day events (start has no time component): add +1 day so a
    //    one-day all-day event renders on the right day.
    //  - Timed events: pass end through unchanged. The previous +1 day
    //    fix made multi-day timed events bleed onto every day they spanned.
    let endDate = event.end_datetime
    const startStr = event.start_datetime || ''
    const startIsAllDay = !startStr.includes('T') || startStr.endsWith('T00:00:00')
    if (endDate && startIsAllDay) {
      const end = new Date(endDate)
      end.setDate(end.getDate() + 1)
      endDate = end.toISOString()
    }
    return {
      id: event.id,
      title: event.title,
      start: event.start_datetime,
      end: endDate,
      // Set color inline so events without a topic class still render
      // visibly. Some events end up tagged 'Other' and FullCalendar's
      // default styling renders them as white-on-white otherwise.
      backgroundColor: color,
      borderColor: color,
      textColor: '#ffffff',
      className: `event-${category.toLowerCase().replace(/\s+/g, '-')}`,
      extendedProps: {
        ...event,
        color,
      },
    }
  }

  const handleEventClick = (info) => {
    setHoveredEvent(null)
    setSelectedEvent(info.event.extendedProps)
  }

  const handleEventMouseEnter = (info) => {
    const rect = info.el.getBoundingClientRect()
    // Use viewport coordinates (no scroll offset) because the tooltip is
    // position: fixed. Position below the event by default; if the event is
    // near the bottom of the viewport, flip above instead.
    const TOOLTIP_HEIGHT_ESTIMATE = 160
    const flipAbove = rect.bottom + TOOLTIP_HEIGHT_ESTIMATE > window.innerHeight
    setTooltipPos({
      x: Math.min(rect.left, window.innerWidth - 380),
      y: flipAbove ? rect.top - TOOLTIP_HEIGHT_ESTIMATE - 4 : rect.bottom + 4,
    })
    // Use FullCalendar's authoritative title and start/end fields to avoid
    // any drift from extendedProps. Pull location/organiser/source from the
    // original event payload we stashed in extendedProps.
    const ext = info.event.extendedProps || {}
    setHoveredEvent({
      title: info.event.title || ext.title || '',
      start_datetime: info.event.start ? info.event.start.toISOString() : ext.start_datetime,
      end_datetime: info.event.end ? info.event.end.toISOString() : ext.end_datetime,
      location: ext.location,
      organiser: ext.organiser,
      source_platform: ext.source_platform,
      categories: ext.categories,
    })
  }

  const handleEventMouseLeave = () => {
    setHoveredEvent(null)
  }

  const handleCategoryToggle = (category) => {
    setSelectedCategories(prev =>
      prev.includes(category)
        ? prev.filter(c => c !== category)
        : [...prev, category]
    )
  }

  const handleRefresh = () => {
    setRefreshKey(prev => prev + 1)
  }

  const handlePrevMonth = () => {
    const [year, month] = currentMonth.split('-').map(Number)
    const date = new Date(year, month - 2, 1)
    setCurrentMonth(date.toISOString().slice(0, 7))
  }

  const handleNextMonth = () => {
    const [year, month] = currentMonth.split('-').map(Number)
    const date = new Date(year, month, 1)
    setCurrentMonth(date.toISOString().slice(0, 7))
  }

  return (
    <div className="container py-4">
      <header className="d-flex justify-content-between align-items-center mb-4">
        <h1 className="h4">KV Events Discovery</h1>
        <div>
          <button className="btn btn-outline-secondary btn-sm me-2" onClick={handleRefresh}>
            Refresh
          </button>
        </div>
      </header>

      <FilterChips
        categories={categories}
        selected={selectedCategories}
        onToggle={handleCategoryToggle}
      />

      <div className="d-flex justify-content-between align-items-center my-3">
        <button className="btn btn-sm btn-outline-primary" onClick={handlePrevMonth}>
          &larr; Previous
        </button>
        <h5 className="mb-0">{(() => {
          const [y, m] = currentMonth.split('-').map(Number)
          return new Date(y, m - 1, 15).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
        })()}</h5>
        <button className="btn btn-sm btn-outline-primary" onClick={handleNextMonth}>
          Next &rarr;
        </button>
      </div>

      {loading ? (
        <div className="text-center py-5">Loading events...</div>
      ) : (
        <div className="card">
          <div className="card-body p-2">
            <FullCalendar
              ref={calendarRef}
              plugins={[dayGridPlugin, interactionPlugin]}
              initialView="dayGridMonth"
              initialDate={(() => { const [y,m] = currentMonth.split('-').map(Number); return new Date(y, m-1, 1) })()}
              events={events}
              eventClick={handleEventClick}
              eventMouseEnter={handleEventMouseEnter}
              eventMouseLeave={handleEventMouseLeave}
              headerToolbar={false}
              height="auto"
              dayMaxEvents={3}
            />
          </div>
        </div>
      )}

      <Legend categories={categories} />

      {hoveredEvent && (
        <div
          className="card shadow"
          style={{
            position: 'fixed',
            top: tooltipPos.y,
            left: tooltipPos.x,
            maxWidth: 360,
            zIndex: 10000,
            pointerEvents: 'none',
            backgroundColor: '#fff',
          }}
        >
          <div className="card-body p-2">
            <div className="fw-semibold small mb-1">
              {hoveredEvent.title || '(untitled event)'}
            </div>
            {(() => {
              const start = hoveredEvent.start_datetime ? new Date(hoveredEvent.start_datetime) : null
              const end = hoveredEvent.end_datetime ? new Date(hoveredEvent.end_datetime) : null
              if (!start || isNaN(start)) return null
              const opts = { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }
              const startStr = start.toLocaleString('en-US', opts)
              if (!end || isNaN(end)) {
                return <div className="text-muted" style={{ fontSize: '0.78rem' }}>{startStr}</div>
              }
              const sameDay = start.toDateString() === end.toDateString()
              const endStr = end.toLocaleString('en-US', sameDay ? { hour: 'numeric', minute: '2-digit' } : opts)
              return (
                <div className="text-muted" style={{ fontSize: '0.78rem' }}>
                  {startStr} → {endStr}
                </div>
              )
            })()}
            {hoveredEvent.location && (
              <div className="text-muted" style={{ fontSize: '0.78rem' }}>
                📍 {hoveredEvent.location}
              </div>
            )}
            {hoveredEvent.organiser && (
              <div className="text-muted" style={{ fontSize: '0.78rem' }}>
                👤 {hoveredEvent.organiser}
              </div>
            )}
            {hoveredEvent.source_platform && (
              <div className="text-muted mt-1" style={{ fontSize: '0.72rem' }}>
                Source:{' '}
                <span className="badge bg-secondary text-white" style={{ fontSize: '0.65rem' }}>
                  {(() => {
                    const src = hoveredEvent.source_platform
                    const labels = {
                      luma: 'Luma',
                      eventbrite: 'Eventbrite',
                      meetup: 'Meetup',
                      eventsize: 'Eventsize',
                      venues: 'Venue',
                      govagency: 'Gov Agency',
                      social: 'Social',
                    }
                    return labels[src] || src
                  })()}
                </span>
              </div>
            )}
            <div className="text-muted mt-1" style={{ fontSize: '0.7rem', fontStyle: 'italic' }}>
              Click for full details
            </div>
          </div>
        </div>
      )}

      {selectedEvent && (
        <EventModal event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      )}
    </div>
  )
}
