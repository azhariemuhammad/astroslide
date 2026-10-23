import React, { useEffect, useState } from 'react';
import moonBefore from '../assets/moon-before.jpg';
import moonAfter from '../assets/moon-after.jpg';
import compositeBefore from '../assets/composite-before.jpg';
import compositeAfter from '../assets/composite-after.jpg';
import '../styles/Landing.css';

// First screen: the Moon fades between before and after, then upload and how it works
const STEPS = [
  { title: 'Add your Moon', text: 'A photo, or video clips from one night.' },
  { title: 'We sharpen and colour it', text: 'The sharpest frames, stacked.' },
  { title: 'Make it yours', text: 'Adjust with sliders or add your stars. Save in 16‑bit.' },
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
      <section className="landing-composite" aria-labelledby="landing-composite-title">
        <p className="landing-eyebrow">New</p>
        <h2 id="landing-composite-title">Put your Moon among your stars</h2>
        <p className="landing-composite-lead">
          Add a star photo from the same night. The sky's glow is cleaned up, the stars behind the Moon
          are hidden (its dark side too), and you drag the Moon where you want it.
        </p>
        <div className="landing-composite-pair">
          <figure>
            <img src={compositeBefore} alt="A gibbous Moon in mineral colour on a black sky" width={600} height={900} loading="lazy" />
            <figcaption>Your Moon</figcaption>
          </figure>
          <span className="landing-composite-arrow" aria-hidden="true">→</span>
          <figure>
            <img src={compositeAfter} alt="The same Moon among a field of stars, with a soft glow beside its lit edge" width={600} height={900} loading="lazy" />
            <figcaption>Among your stars</figcaption>
          </figure>
        </div>
        <p className="landing-footnote">A composite of two photos, and the saved file's name says so.</p>
      </section>

      <p className="landing-footnote">Deep-sky JPEG, TIFF and FITS work too.</p>
    </div>
  );
};

export default Landing;
