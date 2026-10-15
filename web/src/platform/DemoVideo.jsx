import { DEMO_VIDEO } from './site.js'

// The demo video (#demo): a native player on the app's own media path. No autoplay; only the
// metadata loads until the viewer presses play.
export default function DemoVideo() {
  return (
    <div className="content-width page">
      <div className="page-head">
        <p className="kicker"><span className="accent">Platform</span><span className="sep" />Demo video</p>
        <h1 className="display display-xl">The demo <em>video</em>.</h1>
      </div>
      <section className="section">
        <video className="demo-video" src={DEMO_VIDEO.src} poster={DEMO_VIDEO.poster} controls playsInline preload="metadata"
          aria-label="TwinEvidence demo video">
          Your browser cannot play this video.
        </video>
        <p className="hint" style={{ marginTop: 12 }}>About 4 minutes. All data in this demonstration is synthetic.</p>
      </section>
    </div>
  )
}
