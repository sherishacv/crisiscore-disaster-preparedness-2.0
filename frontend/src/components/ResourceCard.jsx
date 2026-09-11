function ResourceCard({ resource, onFocusMap, loading = false }) {
  const hasValidCoordinates =
    Number.isFinite(Number(resource?.lat)) &&
    Number.isFinite(Number(resource?.lon));

  const handleFocusMap = () => {
    if (hasValidCoordinates && onFocusMap) {
      onFocusMap([Number(resource.lat), Number(resource.lon)], 13);
    }
  };

  const getStatus = () => {
    if (loading) {
      return {
        label: 'Searching for nearby resources...',
        className: 'resource-status loading',
      };
    }

    if (!resource) {
      return {
        label: 'Resource data unavailable',
        className: 'resource-status unavailable',
      };
    }

    if (!resource.name) {
      return {
        label: 'Resource information incomplete',
        className: 'resource-status unavailable',
      };
    }

    return null;
  };

  const status = getStatus();

  return (
    <article className="card resource-card">
      <div className="resource-card-header">
        <div className="resource-icon" aria-hidden="true">
          {resource?.icon || '📍'}
        </div>

        <div className="resource-type">
          <span>{resource?.type || 'Emergency Resource'}</span>
        </div>
      </div>

      <div className="resource-copy">
        <h3>{resource?.title || 'Emergency Resource'}</h3>

        {status ? (
          <div className={status.className} role="status">
            {status.label}
          </div>
        ) : (
          <>
            <p className="resource-name">
              {resource.name}
            </p>

            <div className="resource-details">
              <div className="resource-detail">
                <span className="resource-detail-label">Distance</span>
                <span className="resource-detail-value">
                  {resource.distance ?? '--'} km
                </span>
              </div>

              {hasValidCoordinates && (
                <div className="resource-detail">
                  <span className="resource-detail-label">Coordinates</span>
                  <span className="resource-detail-value coordinates">
                    {Number(resource.lat).toFixed(5)}, {Number(resource.lon).toFixed(5)}
                  </span>
                </div>
              )}
            </div>

            <div className="resource-source">
              <span>Source</span>
              <strong>{resource.source || 'OpenStreetMap'}</strong>
            </div>

            {hasValidCoordinates && onFocusMap && (
              <button
                type="button"
                className="resource-map-button"
                onClick={handleFocusMap}
              >
                📍 View on map
              </button>
            )}

            {!hasValidCoordinates && (
              <div className="resource-invalid">
                Location coordinates unavailable
              </div>
            )}
          </>
        )}
      </div>
    </article>
  );
}

export default ResourceCard;