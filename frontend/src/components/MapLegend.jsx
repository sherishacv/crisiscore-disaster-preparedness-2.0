const LEGEND_ITEMS = [
  { key: 'flood', label: 'Flood', color: '#0066cc', icon: '🌊' },
  { key: 'earthquake', label: 'Earthquake', color: '#ff5252', icon: '🌍' },
  { key: 'drought', label: 'Drought', color: '#c68642', icon: '🌵' },
  { key: 'heatwave', label: 'Heatwave', color: '#ff7043', icon: '🔥' },
  { key: 'cyclone', label: 'Cyclone', color: '#7e57c2', icon: '🌀' },
  { key: 'hospital', label: 'Hospital', color: '#ef5350', icon: '🏥' },
  { key: 'shelter', label: 'Shelter', color: '#66bb6a', icon: '🏠' },
  { key: 'unavailable', label: 'Data Unavailable', color: '#78909c', icon: '⬜' },
];

function MapLegend() {
  return (
    <div className="map-legend-panel">
      <strong className="legend-title">Map Legend</strong>
      <div className="legend-grid">
        {LEGEND_ITEMS.map((item) => (
          <span key={item.key} className="legend-item">
            <i className="legend-dot" style={{ background: item.color }} />
            {item.icon} {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export default MapLegend;
