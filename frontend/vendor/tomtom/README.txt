Place TomTom Web SDK files here for local-only loading.

Required filenames (case-sensitive):
- maps-web.min.js
- maps.css

Expected absolute paths on this machine:
- /Users/madhurchaurasia/Documents/GeoInt_projects/Working/version-3/fleet-logistic-sys-v2/frontend/vendor/tomtom/maps-web.min.js
- /Users/madhurchaurasia/Documents/GeoInt_projects/Working/version-3/fleet-logistic-sys-v2/frontend/vendor/tomtom/maps.css

They will be served by FastAPI at:
- http://127.0.0.1:8006/static/vendor/tomtom/maps-web.min.js
- http://127.0.0.1:8006/static/vendor/tomtom/maps.css

Where to get them (version 6.x):
- https://cdn.jsdelivr.net/npm/@tomtom-international/web-sdk-maps@6/dist/
- or https://unpkg.com/@tomtom-international/web-sdk-maps@6/dist/

Note: The app is configured to not use CDNs by default. You must provide these two files locally.
