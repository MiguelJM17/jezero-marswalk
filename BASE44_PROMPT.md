# Prompt for the Base44 editor chat

Attach `openapi.json`, replace `<URL>` with the Cloud Run URL, then paste:

---

Answer in English. The routing API is now live at https://<URL>. Attached is its openapi.json. Use these endpoints exactly:
- POST /api/routes/fastest, /api/routes/easiest, /api/routes/pareto, /api/routes/mineral-target, /api/routes/time-budget, /api/routes/via-shelter
- POST /api/emergency/reachable
- GET /api/health, /api/scientific-destinations, /api/terrain/layers, /api/terrain/point

Request positions are {"waypoint_id": "..."}, {"east_m": .., "north_m": ..} or {"lat": .., "lon": ..}. If "from" is left out, the start is the habitat. Route responses have the same fields as the precomputed routes.json. Errors come as {"error", "detail"}: 404 for an unknown waypoint, 422 for a point outside the map or not walkable.

Rules that must not change:
1. Show "Routing API connected" only after a successful call.
2. If a call fails or times out, keep using the precomputed team files and never invent a result. The first call after the service has been idle can take about 10 seconds, so allow at least 30 seconds before treating a call as failed.
3. Slope above 20 degrees is a warning, never a block. Show the route's "warnings" text.
4. oxygen_verified is always false. Show relative_effort as an estimate in hours of suit supply, not verified oxygen.
5. Minerals are always "probable" detections.
6. The app has English and Spanish (EN | ES selector). Every new text you add must exist in both languages.

Then test Find a Mineral, Plan a Trip and Emergency against the API, and compare with the precomputed values. For carbonate_01 easiest, the values must be 1162.7 m, 29.3 min and 0.77 h. Tell me which screens now call the API and which still use the precomputed files.
