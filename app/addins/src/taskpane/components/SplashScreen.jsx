import { useEffect, useState } from "react";
import logo from "../../assets/c_logo.png";
import React from "react";

const SplashScreen = ({ onComplete }) => {
  const [fadeOut, setFadeOut] = useState(false);

  useEffect(() => {
    const fadeTimer = setTimeout(() => {
      setFadeOut(true);
    }, 4000);

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
        position: "fixed",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        background:
          "linear-gradient(135deg, var(--color-midnight-blue) 0%, var(--color-dark-navy) 100%)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9999,
        opacity: fadeOut ? 0 : 1,
        transition: "opacity 0.5s ease-out",
        overflowY: "auto",
      }}
    >
      {/* Logo Container - Scaled for taskpane */}
      <div
        style={{
          animation: "slideUp 0.8s ease-out",
          marginBottom: "1rem",
        }}
      >
        <img
          src={logo}
          alt="FMS Logo"
          style={{
            width: "200px",
            height: "auto",
            filter: "brightness(0) invert(1)",
            animation: "pulse 2s ease-in-out infinite",
            objectFit: "contain",
          }}
        />
      </div>

      {/* App Title - Smaller text */}
      <div
        style={{
          animation: "slideUp 0.8s ease-out 0.2s backwards",
          textAlign: "center",
          padding: "0 16px",
        }}
      >
        <h1
          style={{
            color: "var(--color-white)",
            fontSize: "1.25rem",
            fontWeight: "700",
            margin: "0 0 0.25rem 0",
            textAlign: "center",
            letterSpacing: "0.05em",
            wordBreak: "break-word",
          }}
        >
          Feasibility Modeling
        </h1>
        <p
          style={{
            color: "var(--color-light-indigo)",
            fontSize: "0.875rem",
            fontWeight: "500",
            margin: 0,
            textAlign: "center",
            letterSpacing: "0.02em",
          }}
        >
          Loading
        </p>
      </div>

      {/* Loading Indicator - Scaled down */}
      <div
        style={{
          marginTop: "1.5rem",
          animation: "slideUp 0.8s ease-out 0.4s backwards",
        }}
      >
        <div
          style={{
            width: "120px",
            height: "3px",
            background: "rgba(140, 170, 238, 0.1)",
            borderRadius: "2px",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: "50%",
              height: "100%",
              background:
                "linear-gradient(90deg, var(--color-brand-blue), var(--color-light-indigo))",
              borderRadius: "2px",
              animation: "loading 1.5s ease-in-out infinite",
            }}
          />
        </div>
      </div>

      <style>
        {`
          @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
          }
          @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.8; transform: scale(0.98); }
          }
          @keyframes loading {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(300%); }
          }
        `}
      </style>
    </div>
  );
};

export default SplashScreen;
