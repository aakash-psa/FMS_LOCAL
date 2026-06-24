import React, { useEffect } from "react";
import { makeStyles } from "@fluentui/react-components";
import { CheckmarkCircle24Regular, ErrorCircle24Regular, Warning24Regular, Dismiss24Regular } from "@fluentui/react-icons";

const useStyles = makeStyles({
  toastContainer: {
    position: "fixed",
    top: "20px",
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: 10000,
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    maxWidth: "400px",
    alignItems: "center",
    justifyContent: "center", // ensure vertical alignment
  },
  toast: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "12px 16px",
    borderRadius: "6px",
    minWidth: "280px",
    maxWidth: "100%",
    boxShadow: "var(--card-shadow)",
    animation: "slideIn 0.3s ease-out",
  },
  success: {
    background: "rgba(140, 170, 238, 0.88)",
    border: "1px solid var(--success-color)",
    color: "var(--color-white)",
  },
  error: {
    background: "rgba(124, 30, 30, 0.9)",
    border: "1px solid var(--error-color)",
    color: "var(--color-white)",
  },
  warning: {
    background: "rgba(202, 158, 230, 0.88)",
    border: "1px solid var(--warning-color)",
    color: "var(--color-white)",
  },
  info: {
    background: "rgba(133, 193, 220, 0.85)",
    border: "1px solid var(--info-color)",
    color: "var(--color-dark-navy)",
  },
  message: {
    flex: 1,
    fontSize: "14px",
    lineHeight: "1.5",
    fontWeight: "500",
  },
  closeButton: {
    background: "none",
    border: "none",
    color: "inherit",
    cursor: "pointer",
    padding: "0",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "20px",
    opacity: 0.7,
    "&:hover": {
      opacity: 1,
    },
  },
  icon: {
    color: "var(--color-white)",
  },
});

export const Toast = ({ message, type = "success", onClose }) => {
  const styles = useStyles();

  const getIcon = () => {
    switch (type) {
      case "success":
        return <CheckmarkCircle24Regular />;
      case "error":
        return <ErrorCircle24Regular />;
      case "warning":
        return <Warning24Regular />;
      default:
        return <CheckmarkCircle24Regular />;
    }
  };

  const getClassName = () => {
    switch (type) {
      case "success":
        return styles.success;
      case "error":
        return styles.error;
      case "warning":
        return styles.warning;
      default:
        return styles.success;
    }
  };

  const handleClose = (e) => {
    e.stopPropagation();
    if (onClose) {
      onClose();
    }
  };

  return (
    <>
      <style>{`
        @keyframes slideIn {
          from { transform: translateX(400px); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
      `}</style>
      <div className={styles.toastContainer}>
        <div className={`${styles.toast} ${getClassName()}`}>
          <span className={styles.icon}>{getIcon()}</span>
          <div className={styles.message}>{message}</div>
          <button
            className={styles.closeButton}
            onClick={handleClose}
            aria-label="Close notification"
            type="button"
          >
            <Dismiss24Regular />
          </button>
        </div>
      </div>
    </>
  );
};

export default Toast;
