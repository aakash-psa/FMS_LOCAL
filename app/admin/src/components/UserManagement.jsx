import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import { userService } from "../services/userService";

const UserManagement = () => {
  const { instance, accounts } = useMsal();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedUsers, setExpandedUsers] = useState({});

  useEffect(() => {
    const fetchUsers = async () => {
      try {
        setLoading(true);
        const userList = await userService.getUsersWithPermissions(instance, accounts[0]);
        setUsers(userList);
        setError(null);
      } catch (err) {
        console.error("Failed to fetch users:", err);
        setError("Failed to load users. Please try again.");
      } finally {
        setLoading(false);
      }
    };

    if (accounts.length > 0) {
      fetchUsers();
    }
  }, [instance, accounts]);

  const refreshUsers = async () => {
    try {
      setLoading(true);
      const userList = await userService.getUsersWithPermissions(instance, accounts[0]);
      setUsers(userList);
      setError(null);
    } catch (err) {
      console.error("Failed to refresh users:", err);
      setError("Failed to refresh users. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const toggleUserProjects = (userId) => {
    setExpandedUsers(prev => ({
      ...prev,
      [userId]: !prev[userId]
    }));
  };

  return (
    <div style={{ padding: "20px", maxWidth: "1200px", margin: "0 auto" }}>
      <div
        style={{
          marginBottom: "20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <h1>User Management</h1>
        <Link
          to="/dashboard"
          style={{ textDecoration: "none", color: "#007bff" }}
        >
          ← Back to Dashboard
        </Link>
      </div>

      <div style={{ marginBottom: "20px", display: "flex", gap: "10px" }}>
        <button
          onClick={refreshUsers}
          style={{
            padding: "10px 20px",
            backgroundColor: "#17a2b8",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "16px",
          }}
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh Users"}
        </button>
      </div>

      <div
        style={{
          backgroundColor: "#fff",
          borderRadius: "8px",
          boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
        }}
      >
        <div style={{ padding: "20px", borderBottom: "1px solid #eee" }}>
          <h3 style={{ margin: 0 }}>Assigned Users ({users.length} users)</h3>
          <p
            style={{ margin: "8px 0 0 0", fontSize: "14px", color: "#6c757d" }}
          >
            Showing only users assigned to this application
          </p>
        </div>

        <div style={{ padding: "20px" }}>
          {loading && (
            <div style={{ textAlign: "center", padding: "20px" }}>
              <p>Loading users...</p>
            </div>
          )}

          {error && (
            <div
              style={{
                padding: "10px",
                backgroundColor: "#f8d7da",
                color: "#721c24",
                border: "1px solid #f5c6cb",
                borderRadius: "4px",
                marginBottom: "20px",
              }}
            >
              {error}
            </div>
          )}

          {!loading && !error && (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ backgroundColor: "#f8f9fa" }}>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid #dee2e6",
                    }}
                  >
                    Display Name
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid #dee2e6",
                    }}
                  >
                    Email
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid #dee2e6",
                    }}
                  >
                    User Principal Name
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid #dee2e6",
                    }}
                  >
                    Account Enabled
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid #dee2e6",
                    }}
                  >
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <>
                    <tr key={user.id}>
                      <td
                        style={{
                          padding: "12px",
                          borderBottom: "1px solid #dee2e6",
                        }}
                      >
                        {user.first_name && user.last_name 
                          ? `${user.first_name} ${user.last_name}`
                          : user.username}
                      </td>
                      <td
                        style={{
                          padding: "12px",
                          borderBottom: "1px solid #dee2e6",
                        }}
                      >
                        {user.email || "N/A"}
                      </td>
                      <td
                        style={{
                          padding: "12px",
                          borderBottom: "1px solid #dee2e6",
                        }}
                      >
                        {user.username}
                      </td>
                      <td
                        style={{
                          padding: "12px",
                          borderBottom: "1px solid #dee2e6",
                        }}
                      >
                        <span
                          style={{
                            padding: "4px 8px",
                            borderRadius: "4px",
                            fontSize: "12px",
                            backgroundColor: user.is_active
                              ? "#d4edda"
                              : "#f8d7da",
                            color: user.is_active ? "#155724" : "#721c24",
                          }}
                        >
                          {user.is_active ? "Active" : "Disabled"}
                        </span>
                      </td>
                      <td
                        style={{
                          padding: "12px",
                          borderBottom: "1px solid #dee2e6",
                        }}
                      >
                        <button
                          style={{
                            marginRight: "8px",
                            padding: "4px 8px",
                            fontSize: "12px",
                            border: "1px solid #007bff",
                            backgroundColor: "transparent",
                            color: "#007bff",
                            borderRadius: "4px",
                            cursor: "pointer",
                          }}
                        >
                          View Details
                        </button>
                        {user.projects && user.projects.length > 0 && (
                          <button
                            onClick={() => toggleUserProjects(user.id)}
                            style={{
                              padding: "4px 8px",
                              fontSize: "12px",
                              border: "1px solid #28a745",
                              backgroundColor: "transparent",
                              color: "#28a745",
                              borderRadius: "4px",
                              cursor: "pointer",
                            }}
                          >
                            {expandedUsers[user.id] ? "Hide" : "Show"} Projects ({user.projects.length})
                          </button>
                        )}
                      </td>
                    </tr>
                    {expandedUsers[user.id] && user.projects && user.projects.length > 0 && (
                      <tr key={`${user.id}-projects`}>
                        <td colSpan="5" style={{ 
                          padding: "0", 
                          backgroundColor: "#f8f9fa",
                          borderBottom: "1px solid #dee2e6"
                        }}>
                          <div style={{ padding: "12px 24px" }}>
                            <h5 style={{ margin: "0 0 12px 0", color: "#495057" }}>
                              Assigned Projects:
                            </h5>
                            <table style={{ 
                              width: "100%", 
                              borderCollapse: "collapse",
                              backgroundColor: "white"
                            }}>
                              <thead>
                                <tr style={{ backgroundColor: "#e9ecef" }}>
                                  <th style={{ padding: "8px", textAlign: "left", fontSize: "13px" }}>
                                    Project Name
                                  </th>
                                  <th style={{ padding: "8px", textAlign: "left", fontSize: "13px" }}>
                                    Read Access
                                  </th>
                                  <th style={{ padding: "8px", textAlign: "left", fontSize: "13px" }}>
                                    Write Access
                                  </th>
                                  <th style={{ padding: "8px", textAlign: "left", fontSize: "13px" }}>
                                    Assigned Date
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {user.projects.map((project) => (
                                  <tr key={project.id}>
                                    <td style={{ padding: "8px", fontSize: "13px", borderBottom: "1px solid #dee2e6" }}>
                                      {project.project_assoc?.name || "N/A"}
                                    </td>
                                    <td style={{ padding: "8px", fontSize: "13px", borderBottom: "1px solid #dee2e6" }}>
                                      <span style={{
                                        padding: "2px 8px",
                                        borderRadius: "4px",
                                        fontSize: "11px",
                                        backgroundColor: project.read_access ? "#d4edda" : "#f8d7da",
                                        color: project.read_access ? "#155724" : "#721c24",
                                      }}>
                                        {project.read_access ? "Yes" : "No"}
                                      </span>
                                    </td>
                                    <td style={{ padding: "8px", fontSize: "13px", borderBottom: "1px solid #dee2e6" }}>
                                      <span style={{
                                        padding: "2px 8px",
                                        borderRadius: "4px",
                                        fontSize: "11px",
                                        backgroundColor: project.write_access ? "#d4edda" : "#f8d7da",
                                        color: project.write_access ? "#155724" : "#721c24",
                                      }}>
                                        {project.write_access ? "Yes" : "No"}
                                      </span>
                                    </td>
                                    <td style={{ padding: "8px", fontSize: "13px", borderBottom: "1px solid #dee2e6" }}>
                                      {project.created_at 
                                        ? new Date(project.created_at).toLocaleDateString()
                                        : "N/A"}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          )}

          {!loading && !error && users.length === 0 && (
            <div style={{ textAlign: "center", padding: "20px" }}>
              <p>No users found.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default UserManagement;
