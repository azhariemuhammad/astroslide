import React, { useEffect, useState } from 'react';
import moonBefore from '../assets/moon-before.jpg';
import moonAfter from '../assets/moon-after.jpg';
import '../styles/Landing.css';

// First screen: the Moon fades between before and after, then upload and how it works
const STEPS = [
  { title: 'Add your Moon', text: 'A photo, or video clips from one night.' },
  { title: 'We sharpen and colour it', text: 'The sharpest frames, stacked.' },
  { title: 'Make it yours', text: 'Adjust with sliders. Save in 16-bit.' },
];

const Landing: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [showAfter, setShowAfter] = useState(true);
  const [paused, setPaused] = useState(
    () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  );

  useEffect(() => {
    if (paused) return;
    const id = window.setInterval(() => setShowAfter(v => !v), 3000);
    return () => window.clearInterval(id);
  }, [paused]);

  // Any click hands control to the viewer, so the auto-fade stops
  const show = (after: boolean) => {
    setPaused(true);
    setShowAfter(after);
  };

  return (
    <div className="landing">
      <section className="landing-hero">
        <button
          type="button"
          className="landing-moon"
          onClick={() => show(!showAfter)}
          aria-label={showAfter ? 'Showing AstroSlide result, click to see the original' : 'Showing the original, click to see the AstroSlide result'}
        >
          <img src={moonBefore} alt="" draggable={false} />
          <img src={moonAfter} alt="" draggable={false} className={`landing-moon-after ${showAfter ? 'visible' : ''}`} />
        </button>
        <div className="landing-toggle" role="group" aria-label="Before or after">
          <button type="button" className={!showAfter ? 'active' : ''} onClick={() => show(false)}>Straight from the telescope</button>
          <button type="button" className={showAfter ? 'active' : ''} onClick={() => show(true)}>Sharpened and coloured</button>
        </div>
        <p className="landing-eyebrow">Free · any telescope · nothing to install</p>
        <h1 className="landing-title">
          Your telescope caught the Moon.<br />
          AstroSlide finds the colour hiding in the grey.
        </h1>
        <p className="landing-lead">
          The colour is real, just too faint for your eye.
        </p>
        <p className="landing-nos">No stacking software. No editing skills. No hours of YouTube tutorials.</p>
      </section>

      <div className="landing-upload">{children}</div>

      <ol className="landing-steps">
        {STEPS.map((s, i) => (
          <li key={s.title}>
            <span className="landing-step-num">{i + 1}</span>
            <div>
              <h2>{s.title}</h2>
              <p>{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="landing-footnote">Deep-sky JPEG, TIFF and FITS work too.</p>
    </div>
  );
};

export default Landing;
