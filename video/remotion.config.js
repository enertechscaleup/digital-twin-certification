// Remotion configuration for the TwinEvidence demo video.
import path from 'node:path'
import { Config } from '@remotion/cli/config'

const here = path.resolve()

Config.setVideoImageFormat('jpeg')
Config.setCodec('h264')
// WebGL in headless Chrome: ANGLE uses the machine's GPU; fall back to --gl=swangle if it fails.
Config.setChromiumOpenGlRenderer('angle')

Config.overrideWebpackConfig((config) => ({
  ...config,
  resolve: {
    ...config.resolve,
    alias: {
      ...(config.resolve?.alias || {}),
      // The wireframe geometry and components are the platform's own (web/src/visual), not a copy.
      '@visual': path.join(here, '../web/src/visual'),
      // One copy of each, even for files imported from web/: React must not be duplicated.
      react: path.join(here, 'node_modules/react'),
      'react-dom': path.join(here, 'node_modules/react-dom'),
      three: path.join(here, 'node_modules/three'),
    },
  },
}))
