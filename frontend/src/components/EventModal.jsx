import React from 'react'

const SOURCE_LABELS = {
  luma: 'Luma',
  eventbrite: 'Eventbrite',
  meetup: 'Meetup',
  eventsize: 'Eventsize',
  venues: 'Venue',
  govagency: 'Government Agency',
  social: 'Social Media',
}

export default function EventModal({ event, onClose }) {
  if (!event) return null

  const formatDate = (dateStr) => {
    if (!dateStr) return 'TBA'
    return new Date(dateStr).toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="modal show d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }} onClick={onClose}>
      <div className="modal-dialog modal-dialog-centered" onClick={e => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">{event.title}</h5>
            <button type="button" className="btn-close" onClick={onClose}></button>
          </div>
          <div className="modal-body">
            <p><strong>Date:</strong> {formatDate(event.start_datetime)}</p>
            {event.end_datetime && <p><strong>End:</strong> {formatDate(event.end_datetime)}</p>}
            <p><strong>Location:</strong> {event.location || 'TBA'}</p>
            {event.is_virtual && <span className="virtual-badge mb-2 d-inline-block">Online</span>}
            <p><strong>Organiser:</strong> {event.organiser || 'TBA'}</p>
            <p><strong>Source:</strong> {SOURCE_LABELS[event.source_platform] || event.source_platform}</p>
            {event.categories?.length > 0 && (
              <p><strong>Categories:</strong> {event.categories.join(', ')}</p>
            )}
            {event.description && (
              <div className="mt-3">
                <strong>Description:</strong>
                <p className="text-muted mt-1">{event.description.slice(0, 500)}...</p>
              </div>
            )}
          </div>
          <div className="modal-footer">
            {event.source_url && (
              <a href={event.source_url} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
                Register / Learn More
              </a>
            )}
            <button type="button" className="btn btn-secondary" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    </div>
  )
}