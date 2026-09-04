function AlertPanel({ alerts, loading }) {
  if (loading) {
    return (
      <div className="card alerts-panel">
        <div className="section-header compact">
          <h2>🚨 ALERTS</h2>
          <span className="status-pill">Loading...</span>
        </div>
        <p className="panel-note">Monitoring for detected high-severity events...</p>
      </div>
    );
  }

  if (!alerts || alerts.length === 0) {
    return (
      <div className="card alerts-panel">
        <div className="section-header compact">
          <h2>🚨 ALERTS</h2>
          <span className="status-pill">0 Active</span>
        </div>
        <p className="panel-note">No active alerts from detected high-severity events.</p>
      </div>
    );
  }

  return (
    <div className="card alerts-panel">
      <div className="section-header compact">
        <h2>🚨 ALERTS</h2>
        <span className="status-pill">{alerts.length} Active</span>
      </div>

      <div className="alert-list">
        {alerts.map((alert) => {
          const typeIcon = alert.disaster_type === 'earthquake' ? '🌍'
            : alert.disaster_type === 'flood' ? '🌊'
            : alert.disaster_type === 'heatwave' ? '🔥'
            : alert.disaster_type === 'cyclone' ? '🌀'
            : alert.disaster_type === 'drought' ? '🌵'
            : '⚠';
          
          return (
            <div key={alert.id} className={`alert-row ${alert.severity}`}>
              <span className="alert-dot" />
              <div className="alert-content">
                <div className="alert-header">
                  <strong>{typeIcon} {alert.title}</strong>
                  {alert.source && <span className="alert-source">{alert.source}</span>}
                </div>
                <p className="alert-detail">{alert.detail}</p>
                {alert.lat != null && alert.lon != null && (
                  <small className="alert-location">
                    📍 {alert.lat.toFixed(2)}, {alert.lon.toFixed(2)}
                  </small>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default AlertPanel;
