export const state = {
  map: null,
  mapReady: false,
  userCircle: null,
  leafletMarkers: [],
  cardMap: new Map(),
  currentMode: 'autopilot',
  lastAutopilotPlace: null,
  recFallback: null,
  planCustomLocation: null,
  planMapClickActive: false,
  planCustomMarker: null,
};
