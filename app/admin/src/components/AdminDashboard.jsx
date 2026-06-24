import { useState, useEffect } from "react";
import { useAdminRole } from "../hooks/useAdminRole";
import { useNavigate } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import { projectService } from "../services/projectService";
import { userService } from "../services/userService";
import Icon from "./Icon";

const AdminDashboard = () => {
  const { isAdmin, loading } = useAdminRole();
  const navigate = useNavigate();
  const { instance, accounts } = useMsal();
  const [stats, setStats] = useState({
    projectCount: 0,
    userCount: 0,
    loading: true,
  });
  const [syncStatus, setSyncStatus] = useState({
    syncing: false,
    synced: false,
    error: null,
  });

  // Sync users on component mount
  useEffect(() => {
    const syncUsers = async () => {
      if (
        accounts.length > 0 &&
        isAdmin &&
        !syncStatus.synced &&
        !syncStatus.syncing
      ) {
        setSyncStatus((prev) => ({ ...prev, syncing: true }));

        try {
          // Get all users from Microsoft Graph
          const users = await userService.getAllUsers(instance, accounts[0]);

          // Sync users to database
          const syncResult = await userService.syncUsersToDatabase(
            instance,
            accounts[0],
            users
          );

          setSyncStatus({ syncing: false, synced: true, error: null });
        } catch (error) {
          console.error("Failed to sync users:", error);
          setSyncStatus({
            syncing: false,
            synced: false,
            error: error.message,
          });
        }
      }
    };

    if (!loading && isAdmin) {
      syncUsers();
    }
  }, [instance, accounts, isAdmin, loading]);

  useEffect(() => {
    const fetchStats = async () => {
      if (accounts.length > 0 && isAdmin) {
        try {
          const projectCountData = await projectService.getProjectCount(
            instance,
            accounts[0]
          );

          setStats({
            projectCount: projectCountData.project_count || 0,
            userCount: projectCountData.user_count || 0,
            loading: false,
          });
        } catch (error) {
          console.error("Error fetching dashboard stats:", error);
          setStats((prev) => ({ ...prev, loading: false }));
        }
      }
    };

    if (!loading && isAdmin && syncStatus.synced) {
      fetchStats();
    }
  }, [instance, accounts, isAdmin, loading, syncStatus.synced]);

  if (loading) {
    return (
      <div style={{ padding: "20px", textAlign: "center", backgroundColor: "var(--bg-primary)", minHeight: "100vh" }}>
        <h2 style={{ color: "var(--text-primary)" }}>Loading...</h2>
        <p style={{ color: "var(--text-secondary)" }}>Checking admin permissions...</p>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div
        style={{
          padding: "20px",
          textAlign: "center",
          border: "1px solid var(--color-falu-red)",
          backgroundColor: "var(--error-bg)",
          color: "var(--error-text)",
          margin: "20px",
          borderRadius: "8px",
        }}
      >
        <h2>Access Denied</h2>
        <p>You do not have admin rights to access this dashboard.</p>
      </div>
    );
  }

  const handleProjectManagement = () => {
    navigate("/projects");
  };

  const handleUserManagement = () => {
    navigate("/users");
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">Admin Dashboard</h1>
        <p className="dashboard-subtitle">
          Manage your projects and users efficiently
        </p>
        {syncStatus.syncing && (
          <div
            style={{
              marginTop: "12px",
              padding: "8px 16px",
              backgroundColor: "var(--success-bg)",
              color: "var(--success-text)",
              border: "1px solid var(--success-color)",
              borderRadius: "6px",
              fontSize: "14px",
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              fontWeight: "500",
            }}
          >
            <Icon icon="material-symbols:sync-outline" size={20} />
            Syncing users...
          </div>
        )}
        {syncStatus.error && (
          <div
            style={{
              marginTop: "12px",
              padding: "8px 16px",
              backgroundColor: "var(--error-bg)",
              color: "var(--error-text)",
              border: "1px solid var(--error-color)",
              borderRadius: "6px",
              fontSize: "14px",
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <Icon icon="material-symbols:error-outline" size={20} />
            Sync failed: {syncStatus.error}
          </div>
        )}
      </div>

      <div className="dashboard-stats">
        <div className="stat-item">
          <span className="stat-number">
            {stats.loading ? "..." : stats.projectCount}
          </span>
          <span className="stat-label">Projects</span>
        </div>
        <div className="stat-item">
          <span className="stat-number">
            {stats.loading ? "..." : stats.userCount}
          </span>
          <span className="stat-label">Total Users</span>
        </div>
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-card" onClick={handleProjectManagement}>
          <h4>
            <Icon icon="material-symbols:folder-open-outline" size={28} />
            Project Management
          </h4>
          <p>
            Create, edit, and manage projects. Track project progress, assign
            team members, and monitor deadlines efficiently.
          </p>
        </div>
      </div>
    </div>
  );
};

export default AdminDashboard;
