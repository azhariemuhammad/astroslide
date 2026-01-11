import { useNavigate } from 'react-router-dom';
import demoMoonImage from '../assets/demo-moon.jpeg';

export default function LandingPage() {
  const navigate = useNavigate();

  const goToEditor = () => {
    navigate('/editor');
  };

  return (
    <div className="landing-page">
      {/* Navigation */}
      <nav className="landing-nav">
        <div className="nav-left">
          <span className="nav-logo">
            <span className="logo-icon">✨</span>
            AstroSlide
          </span>
        </div>
        <div className="nav-right">
          <button className="landing-nav-btn" onClick={goToEditor}>
            Try Now
          </button>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="landing-hero">
        <div className="hero-content">
          <span className="hero-badge">
            <span className="badge-dot"></span>
            AI-Powered Enhancement
          </span>
          <h1 className="hero-title">
            Transform your telescope images<br />
            <span className="hero-highlight">in one click</span>
          </h1>
          <p className="hero-subtitle">
            AstroSlide's AI enhances your smart telescope captures—reducing noise, 
            removing gradients, and bringing out stunning details instantly.
          </p>
          <div className="hero-actions">
            <button className="hero-cta-primary" onClick={goToEditor}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="20" height="20">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              Upload Image
            </button>
            <button className="hero-cta-secondary" onClick={() => document.getElementById('features')?.scrollIntoView({behavior: 'smooth'})}>
              Learn More
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18" height="18">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          </div>
        </div>
        <div className="hero-demo">
          <div className="demo-container">
            <div className="demo-labels">
              <span className="demo-label demo-label-before">Before</span>
              <span className="demo-label demo-label-after">After</span>
            </div>
            <div className="demo-image-wrapper">
              <img src={demoMoonImage} alt="Enhanced telescope capture" className="demo-image" />
              <div className="demo-overlay">
                <div className="demo-slider-line"></div>
                <div className="demo-slider-handle">
                  <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                    <path d="M8 5v14l-7-7 7-7zm8 0v14l7-7-7-7z" />
                  </svg>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="landing-features" id="features">
        <h2 className="section-title">Powerful Enhancement Features</h2>
        <p className="section-subtitle">Optimized for smart telescope captures from Seestar, Dwarf, Vaonis, and more</p>
        <div className="features-grid">
          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="28" height="28">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </div>
            <h3 className="feature-title">Smart Noise Reduction</h3>
            <p className="feature-description">AI-powered denoising preserves fine stellar details while eliminating sensor noise from short exposures.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="28" height="28">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            </div>
            <h3 className="feature-title">Gradient Removal</h3>
            <p className="feature-description">Automatically removes light pollution gradients and vignetting for clean, even backgrounds.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="28" height="28">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
              </svg>
            </div>
            <h3 className="feature-title">Color Calibration</h3>
            <p className="feature-description">Balanced color correction brings out natural hues in nebulae, galaxies, and planetary surfaces.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="28" height="28">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
              </svg>
            </div>
            <h3 className="feature-title">Star Enhancement</h3>
            <p className="feature-description">Sharpens stars and brings out fine detail in clusters and stellar fields.</p>
          </div>
        </div>
      </section>

      {/* How It Works Section */}
      <section className="landing-how-it-works">
        <h2 className="section-title">How It Works</h2>
        <p className="section-subtitle">Get stunning results in three simple steps</p>
        <div className="steps-container">
          <div className="step-card">
            <div className="step-number">1</div>
            <div className="step-content">
              <h3 className="step-title">Upload</h3>
              <p className="step-description">Drag and drop or select your telescope capture (JPEG, PNG, TIFF, or FITS)</p>
            </div>
          </div>
          <div className="step-connector">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="24" height="24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </div>
          <div className="step-card">
            <div className="step-number">2</div>
            <div className="step-content">
              <h3 className="step-title">Enhance</h3>
              <p className="step-description">Choose a preset and let our AI process your image automatically</p>
            </div>
          </div>
          <div className="step-connector">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="24" height="24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </div>
          <div className="step-card">
            <div className="step-number">3</div>
            <div className="step-content">
              <h3 className="step-title">Compare & Download</h3>
              <p className="step-description">Use the slider to compare before/after, then download your enhanced image</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="landing-cta">
        <div className="cta-content">
          <h2 className="cta-title">Ready to enhance your telescope photos?</h2>
          <p className="cta-subtitle">No sign-up required. Free to use.</p>
          <button className="cta-button" onClick={goToEditor}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="22" height="22">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
            </svg>
            Get Started Now
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <p>© 2026 AstroSlide. Made for smart telescope enthusiasts.</p>
      </footer>
    </div>
  );
}
