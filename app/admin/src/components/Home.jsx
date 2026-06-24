import { useIsAuthenticated } from "@azure/msal-react";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import LoginComponent from "./LoginComponent";
import { useAdminRole } from "../hooks/useAdminRole";

const Home = () => {
  const isAuthenticated = useIsAuthenticated();
  const { isAdmin, loading } = useAdminRole();
  const navigate = useNavigate();

  useEffect(() => {
    if (isAuthenticated && !loading) {
      if (isAdmin) {
        navigate("/dashboard");
      }
    }
  }, [isAuthenticated, isAdmin, loading, navigate]);

  if (!isAuthenticated) {
    return (
      <div
        style={{
          textAlign: "center",
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          backgroundColor: "var(--bg-primary)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-color)",
          borderRadius: "8px",
          boxShadow: "var(--card-shadow)",
        }}
      >
        <h1 style={{ color: "var(--text-primary)" }}>Admin Panel</h1>
        <p style={{ color: "var(--text-secondary)" }}>
          Please sign in to access the admin dashboard
        </p>
        <LoginComponent />
      </div>
    );
  }

  if (loading) {
    return (
      <div
        style={{
          textAlign: "center",
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          backgroundColor: "var(--bg-primary)",
          color: "var(--text-primary)",
        }}
      >
        <h1 style={{ color: "var(--text-primary)" }}>Admin Panel</h1>
        <p style={{ color: "var(--text-secondary)" }}>Checking admin permissions...</p>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div
        style={{
          textAlign: "center",
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          backgroundColor: "var(--bg-primary)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-color)",
          borderRadius: "8px",
          boxShadow: "var(--card-shadow)",
          margin: "20px",
        }}
      >
        <h1 style={{ color: "var(--text-primary)" }}>Admin Panel</h1>
        <h2 style={{ color: "var(--error-text)" }}>Access Denied</h2>
        <p style={{ color: "var(--text-secondary)" }}>
          You do not have admin privileges to access this application.
        </p>
        <LoginComponent />
      </div>
    );
  }

  // This shouldn't be reached due to useEffect redirect, but just in case
  return null;
};

export default Home;
