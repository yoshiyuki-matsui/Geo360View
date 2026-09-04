Photo Sphere Viewer vendor files are not bundled in this prototype.

Place local ESM/CSS files here to test `?engine=psv`:

- `three/three.module.js`
- `three/three.core.js`
- `core/index.module.js`
- `core/index.css`
- `markers-plugin/index.module.js`
- `markers-plugin/index.css`

The viewer reuses the existing `/frames/...` image endpoint and
`/api/session/...` JSON endpoints.

This directory is intentionally a local vendor copy for the krpano replacement
experiment. The application does not run npm at QGIS plugin runtime.

When refreshing files from npm tarballs, copy at least:

- `@photo-sphere-viewer/core/package/index.module.js`
- `@photo-sphere-viewer/core/package/index.css`
- `@photo-sphere-viewer/markers-plugin/package/index.module.js`
- `@photo-sphere-viewer/markers-plugin/package/index.css`
- `three/package/build/three.module.js`
- `three/package/build/three.core.js`

The `three.core.js` file must stay beside `three.module.js` because
`three.module.js` imports it as `./three.core.js`.
