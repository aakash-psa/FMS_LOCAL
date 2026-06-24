import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Button, makeStyles } from "@fluentui/react-components";
import {
  ArrowLeft24Regular,
  Home24Regular,
  SignOut24Regular,
  Shield24Regular,
} from "@fluentui/react-icons";
import { useAuth } from "../../msal/AuthProvider";
import { openAdminPanel } from "../../services/adminUtils";

const useStyles = makeStyles({
  navigationHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px",
    padding: "8px 12px",
    background: "var(--bg-secondary)",
    borderBottom: "1px solid var(--border-color)",
  },
  leftSection: {
    display: "flex",
    gap: "8px",
  },
  navButton: {
    background: "var(--bg-tertiary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
    minWidth: "40px",
    opacity: 0.8,
    "&:hover": {
      background: "var(--accent-hover)",
    },

    /* 🔥 Fix disabled styling */
    "&:disabled": {
      background: "var(--bg-tertiary)",
      color: "var(--text-primary)", // keep icon/text white
      opacity: 1, // prevent Fluent from greying it out
      cursor: "not-allowed",
    },

    /* Make sure the SVG icon also stays white */
    "&:disabled svg": {
      color: "var(--text-primary)",
      fill: "var(--text-primary)",
    },
  },
  signOutButton: {
    background: "var(--error-color)",
    color: "var(--text-primary)",
    border: "1px solid var(--error-color)",
    "&:hover": {
      background: "var(--error-color)",
    },
  },
});

const Header = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { signOut } = useAuth();
  const styles = useStyles();

  const handleBack = () => {
    navigate(-1);
  };

  const handleHome = () => {
    navigate("/");
  };

  const handleSignOut = async () => {
    try {
      await signOut();
      // The App component will detect isAuthenticated is false and show SignIn
    } catch (error) {
      console.error("Sign out error:", error);
    }
  };

  const isHomePage = location.pathname === "/";

  return (
    <div className={styles.navigationHeader}>
      <div className={styles.leftSection}>
        <Button
          className={styles.navButton}
          icon={<ArrowLeft24Regular />}
          onClick={handleBack}
          title="Go Back"
        />
        <Button
          className={styles.navButton}
          icon={<Home24Regular />}
          onClick={handleHome}
          title="Go Home"
          disabled={isHomePage}
        />
      </div>
      <div className={styles.leftSection}>
        <Button
          className={styles.navButton}
          icon={<Shield24Regular />}
          onClick={openAdminPanel}
          title="Open Admin Panel - Manage projects, users, and scenarios"
        />
        <Button
          className={styles.signOutButton}
          icon={<SignOut24Regular />}
          onClick={handleSignOut}
          title="Sign Out"
        >
          Sign Out
        </Button>
      </div>
    </div>
  );
};

export default Header;
