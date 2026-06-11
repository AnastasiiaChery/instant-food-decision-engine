export const state = {
  map: null,
  mapReady: false,
  userCircle: null,
  leafletMarkers: [],
  cardMap: new Map(),
  currentMode: 'autopilot',
  autopilotSeen: [],  // names already shown this session — excluded on "try again"
  recFallback: null,
  planCustomLocation: null,
  planMapClickActive: false,
  planCustomMarker: null,
};
