import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import { Link } from "react-router-dom";
import { useAdminRole } from "../hooks/useAdminRole";
import Icon from "./Icon";
import PSLogo from '../assets/ps_logo.png';

const Navigation = () => {
  const isAuthenticated = useIsAuthenticated();
  const { isAdmin } = useAdminRole();
  const { instance } = useMsal();

  const handleLogout = () => {
    instance.logoutPopup().catch((e) => {
      console.error(e);
    });
  };

  if (!isAuthenticated || !isAdmin) {
    return null;
  }

  return (
    <header
      style={{
        width: "100%",
        padding: "1.25rem 2rem",
        position: "sticky",
        top: 0,
        zIndex: 1000,
      }}
    >
      <nav
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          maxWidth: "1400px",
          margin: "0 auto",
          padding: "1rem 1.5rem",
          borderRadius: "250px",
          background: "linear-gradient(90deg, rgba(140, 170, 238, 0.12), rgba(202, 158, 230, 0.08))",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          border: "1px solid rgba(186, 187, 241, 0.1)",
          boxShadow: "0 4px 16px rgba(0, 0, 0, 0.2)",
          position: "relative",
          overflow: "hidden",
          transition: "all 0.3s ease",
        }}
      >
        {/* Overlay effect */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            background: "rgba(0, 0, 0, 0.05)",
            pointerEvents: "none",
            transition: "all 0.7s",
            zIndex: -1,
          }}
        />

        {/* Logo Section */}
        <Link
          to="/dashboard"
          style={{ 
            textDecoration: "none", 
            color: "var(--color-white)", 
            display: "flex", 
            alignItems: "center", 
            gap: "12px",
            transition: "all 0.3s",
            zIndex: 1,
          }}
          onMouseOver={(e) => e.currentTarget.style.opacity = "0.85"}
          onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
        >
          <img
            src={PSLogo}
            alt="Preferred Square"
            style={{
              height: "48px",
              width: "auto",
              filter: "brightness(0) invert(1)",
            }}
          />
          <span
            style={{
              display: "inline-block",
              width: "1px",
              height: "32px",
              background: "rgba(255, 255, 255, 0.3)",
              margin: "0 4px",
            }}
          />
          <h1
            style={{
              margin: 0,
              fontSize: "1rem",
              fontWeight: "700",
              color: "var(--color-white)",
              lineHeight: 1.2,
              letterSpacing: "0.02em",
            }}
          >
            Admin Dashboard
          </h1>
        </Link>

        {/* Right Actions */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: "1rem",
          zIndex: 1,
        }}>
          <button
            onClick={handleLogout}
            style={{
              padding: "0.625rem 1.5rem",
              background: "linear-gradient(135deg, var(--color-btn-primary) 0%, var(--color-btn-primary-hover) 100%)",
              color: "var(--color-white)",
              border: "none",
              borderRadius: "300px",
              cursor: "pointer",
              fontSize: "0.875rem",
              fontWeight: "700",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              transition: "all 0.5s",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              boxShadow: "0 2px 8px rgba(140, 170, 238, 0.15)",
              whiteSpace: "nowrap",
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.background = "linear-gradient(135deg, var(--color-light-indigo) 0%, var(--color-ps-purple) 100%)";
              e.currentTarget.style.transform = "translateY(-2px)";
              e.currentTarget.style.boxShadow = "0 4px 12px rgba(140, 170, 238, 0.25)";
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.background = "linear-gradient(135deg, var(--color-btn-primary) 0%, var(--color-btn-primary-hover) 100%)";
              e.currentTarget.style.transform = "translateY(0)";
              e.currentTarget.style.boxShadow = "0 2px 8px rgba(140, 170, 238, 0.15)";
            }}
          >
            <Icon icon="material-symbols:logout-outline" size={16} />
            Sign Out
          </button>
        </div>
      </nav>
    </header>
  );
};

export default Navigation;
