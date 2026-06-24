import { useEffect, useState } from 'react';
import PS_logo from '../assets/ps_logo.png';

const SplashScreen = ({ onComplete }) => {
  const [fadeOut, setFadeOut] = useState(false);

  useEffect(() => {
    // Start fade out after 2 seconds
    const fadeTimer = setTimeout(() => {
      setFadeOut(true);
    }, 4000);

    // Complete after fade out animation (2.5 seconds total)
    const completeTimer = setTimeout(() => {
      onComplete();
    }, 4500);

    return () => {
      clearTimeout(fadeTimer);
      clearTimeout(completeTimer);
    };
  }, [onComplete]);

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        background: 'linear-gradient(135deg, var(--color-midnight-blue) 0%, var(--color-dark-navy) 100%)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        opacity: fadeOut ? 0 : 1,
        transition: 'opacity 0.5s ease-out',
      }}
    >
      {/* Logo Container with Animation */}
      <div
        style={{
          animation: 'slideUp 0.8s ease-out',
          marginBottom: '2rem',
        }}
      >
        <img
          src={PS_logo}
          alt="Preferred Square"
          style={{
            width: '320px',
            height: 'auto',
            filter: 'brightness(0) invert(1)',
            animation: 'pulse 2s ease-in-out infinite',
          }}
        />
      </div>

      {/* App Title */}
      <div
        style={{
          animation: 'slideUp 0.8s ease-out 0.2s backwards',
        }}
      >
        <h1
          style={{
            color: 'var(--color-white)',
            fontSize: '2.5rem',
            fontWeight: '700',
            margin: '0 0 0.5rem 0',
            textAlign: 'center',
            letterSpacing: '0.05em',
          }}
        >
          Feasibility Modeling Solution
        </h1>
        <p
          style={{
            color: 'var(--color-light-indigo)',
            fontSize: '1.125rem',
            fontWeight: '500',
            margin: 0,
            textAlign: 'center',
            letterSpacing: '0.02em',
          }}
        >
          Admin Dashboard
        </p>
      </div>

      {/* Loading Indicator */}
      <div
        style={{
          marginTop: '3rem',
          animation: 'slideUp 0.8s ease-out 0.4s backwards',
        }}
      >
        <div
          style={{
            width: '200px',
            height: '4px',
            background: 'rgba(140, 170, 238, 0.1)',
            borderRadius: '2px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: '50%',
              height: '100%',
              background: 'linear-gradient(90deg, var(--color-brand-blue), var(--color-light-indigo))',
              borderRadius: '2px',
              animation: 'loading 1.5s ease-in-out infinite',
            }}
          />
        </div>
      </div>

      {/* Keyframe Animations */}
      <style>
        {`
          @keyframes slideUp {
            from {
              opacity: 0;
              transform: translateY(20px);
            }
            to {
              opacity: 1;
              transform: translateY(0);
            }
          }

          @keyframes pulse {
            0%, 100% {
              opacity: 1;
              transform: scale(1);
            }
            50% {
              opacity: 0.8;
              transform: scale(0.98);
            }
          }

          @keyframes loading {
            0% {
              transform: translateX(-100%);
            }
            100% {
              transform: translateX(300%);
            }
          }
        `}
      </style>
    </div>
  );
};

export default SplashScreen;
