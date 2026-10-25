# Sentinel Robotics Architecture

## Theme 4 evaluation boundary

The authoritative simulation snapshot lives in `backend/main.py` and is consumed by the existing fleet, failure analysis, migration, admin, export, and PDF routes. The Theme 4 Compliance / Evaluation Engine derives availability, mission preservation, cascade depth, containment, battery reserve, migration efficiency, and prediction evaluation from that snapshot.

## Frontend architecture

Vite serves the React application. `src/App.jsx` owns the lightweight route switch and authentication boundary. The product surface is limited to operations, fleet, missions, failure analysis, recovery, digital twin, evaluation, fleet alerts, profile, and admin. `Theme4Page` adds the protected judge-facing evaluation surface and uses `src/services/simulation.js` for API calls.

## Backend architecture

FastAPI exposes simulation state, failure prediction, propagation, recovery, migration, admin, exports, PDF reports, and WebSocket connectivity. The new `/api/theme4/*` endpoints provide failure injection, progressive stages, seeded sequence generation, scenario execution, reset, evaluation, and a cloned-state benchmark.

## Simulation and prediction

The simulator is deterministic for a supplied seed when generating failure sequences. A failure injection changes the authoritative robot health/status, appends a failure and prediction record, and emits timeline events. Predictions are simulation-based heuristics; they are not presented as trained-model accuracy. Precision, recall, and F1 are returned only with an explicit evaluation population.

## Propagation, criticality, migration, and rebalancing

The current migration engine remains the owner of task reassignment and destination selection. The compliance engine reads migration history and the mission/task relationships already present in the snapshot. The evaluation API reports the resulting chain and recovery metrics without replacing the existing engine.

## Reporting and exports

The existing JSON, CSV, and PDF report infrastructure remains available. The Theme 4 page exports its current evaluation snapshot as JSON. PDF generation accepts the same snapshot contract and is the source for the existing branded report.

## Authentication and deployment

Google/Firebase authentication, admin authentication, and Demo Mode are preserved. Protected operational routes continue to require the existing client-side authentication boundary. Deployment remains environment-specific: configure the frontend API URL, Firebase web variables, backend CORS, Firebase Admin credentials, and admin secret through environment variables. No deployment URL is claimed here because this workspace does not contain a verified public deployment.
