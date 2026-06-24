import { useState, useEffect } from "react";
import { Link, useParams, useNavigate, useLocation } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import { projectService } from "../services/projectService";
import { userService } from "../services/userService";

const AssignUser = () => {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { instance, accounts } = useMsal();
  const [project, setProject] = useState(location.state?.project || null);
  const [availableUsers, setAvailableUsers] = useState([]);
  const [assignedUsers, setAssignedUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [loadingProject, setLoadingProject] = useState(!location.state?.project);
  const [error, setError] = useState(null);
  const [userPermissions, setUserPermissions] = useState({});
  const [searchQuery, setSearchQuery] = useState("");
  const [editingPermissions, setEditingPermissions] = useState({});
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isAssignModalOpen, setIsAssignModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [modalPermissions, setModalPermissions] = useState({
    read_access: false,
    write_access: false
  });
  const [isProcessing, setIsProcessing] = useState(false);

  useEffect(() => {
    fetchProjectAndUsers();
  }, [projectId, instance, accounts]);

  const fetchProjectAndUsers = async () => {
    try {
      // Only fetch project if not passed via state
      if (!location.state?.project) {
        setLoadingProject(true);
        const projects = await projectService.getAllProjects(instance, accounts[0]);
        const projectsData = Array.isArray(projects) ? projects : (projects.projects || projects.data || []);
        const currentProject = projectsData.find(p => p.id === projectId);
        
        if (currentProject) {
          setProject(currentProject);
        } else {
          setError("Project not found");
        }
        setLoadingProject(false);
      }

      setLoadingUsers(true);
      
      // Fetch assigned users for this project
      const projectUsers = await projectService.getProjectUsers(instance, accounts[0], projectId);
      const assignedUsersList = projectUsers || [];
      setAssignedUsers(assignedUsersList);
      
      // Fetch all users from backend database with their permissions
      const allUsersWithPermissions = await userService.getUsersWithPermissions(instance, accounts[0]);
      
      // Map to format compatible with the component
      const mappedUsers = allUsersWithPermissions.map(user => ({
        id: user.username, // Use username as unique identifier
        displayName: user.first_name && user.last_name 
          ? `${user.first_name} ${user.last_name}`
          : user.username,
        mail: user.email,
        userPrincipalName: user.email,
        accountEnabled: user.is_active
      }));
      
      setAvailableUsers(mappedUsers);
      
      setError(null);
    } catch (err) {
      console.error("Failed to fetch data:", err);
      setError("Failed to load data. Please try again.");
    } finally {
      setLoadingUsers(false);
    }
  };

  // Helper function to check if user is already assigned
  const isUserAssigned = (userId) => {
    return assignedUsers.some(au => au.user?.username === userId);
  };

  // Helper function to check if user has any active permissions
  const hasActivePermissions = (userId) => {
    const assignedUser = assignedUsers.find(au => au.user?.username === userId);
    return assignedUser && (assignedUser.read_access || assignedUser.write_access);
  };

  // Helper function to get assigned user permissions
  const getAssignedUserPermissions = (userId) => {
    const assignedUser = assignedUsers.find(au => au.user?.username === userId);
    return assignedUser;
  };

  // Filter users based on search query
  const filteredUsers = availableUsers.filter(user => {
    const searchLower = searchQuery.toLowerCase();
    const displayName = (user.displayName || "").toLowerCase();
    const email = (user.mail || user.userPrincipalName || "").toLowerCase();
    return displayName.includes(searchLower) || email.includes(searchLower);
  });

  const handlePermissionChange = (userId, permission, isChecked) => {
    setUserPermissions(prev => {
      const current = prev[userId] || [];
      let updated;

      if (isChecked) {
        if (permission === "Write" && !current.includes("Read")) {
          updated = [...current, "Read", permission];
        } else if (!current.includes(permission)) {
          updated = [...current, permission];
        } else {
          updated = current;
        }
      } else {
        if (permission === "Read" && current.includes("Write")) {
          return prev; // Cannot remove read if write is selected
        }
        updated = current.filter(p => p !== permission);
      }

      return { ...prev, [userId]: updated };
    });
  };

  const handleAssignUser = async (userId) => {
    const permissions = userPermissions[userId] || [];
    
    if (permissions.length === 0) {
      alert("Please select at least one permission (Read or Write)");
      return;
    }

    try {
      const userData = {
        user_id: userId,
        read_access: permissions.includes("Read") || permissions.includes("Write"),
        write_access: permissions.includes("Write")
      };

      await projectService.assignUserToProject(
        instance,
        accounts[0],
        projectId,
        userData
      );

      alert("User assigned successfully!");
      
      // Reset permissions for this user
      setUserPermissions(prev => {
        const updated = { ...prev };
        delete updated[userId];
        return updated;
      });

      // Refresh the user list to show updated assignments
      await fetchProjectAndUsers();
    } catch (error) {
      console.error("Failed to assign user:", error);
      alert("Failed to assign user. Please try again.");
    }
  };

  const openAssignModal = (user) => {
    const assignedData = getAssignedUserPermissions(user.id);
    setSelectedUser(user);
    
    // If user is already assigned, pre-fill with current permissions
    if (assignedData) {
      setModalPermissions({
        read_access: assignedData.read_access,
        write_access: assignedData.write_access
      });
    } else {
      setModalPermissions({
        read_access: false,
        write_access: false
      });
    }
    
    setIsAssignModalOpen(true);
  };

  const closeAssignModal = () => {
    setIsAssignModalOpen(false);
    setSelectedUser(null);
    setModalPermissions({
      read_access: false,
      write_access: false
    });
  };

  const handleModalPermissionChange = (permission, isChecked) => {
    setModalPermissions(prev => {
      const updated = { ...prev };
      
      if (permission === 'write_access') {
        if (isChecked) {
          // Auto-enable read when write is enabled
          updated.read_access = true;
          updated.write_access = true;
        } else {
          updated.write_access = false;
        }
      } else if (permission === 'read_access') {
        if (!isChecked && updated.write_access) {
          // Cannot disable read if write is enabled
          return prev;
        }
        updated.read_access = isChecked;
      }
      
      return updated;
    });
  };

  const handleSavePermissions = async () => {
    if (!modalPermissions.read_access && !modalPermissions.write_access) {
      alert("Please select at least one permission (Read or Write)");
      return;
    }

    setIsProcessing(true);
    
    try {
      const isAlreadyAssigned = isUserAssigned(selectedUser.id);
      
      if (isAlreadyAssigned) {
        // Use edit API for already assigned users
        await projectService.updateUserPermission(
          instance,
          accounts[0],
          projectId,
          selectedUser.id,
          modalPermissions
        );
        alert("Permissions updated successfully!");
      } else {
        // Use assign API for new users
        const userData = {
          user_id: selectedUser.id,
          ...modalPermissions
        };
        
        await projectService.assignUserToProject(
          instance,
          accounts[0],
          projectId,
          userData
        );
        alert("User assigned successfully!");
      }
      
      closeAssignModal();
      await fetchProjectAndUsers();
    } catch (error) {
      console.error("Failed to save permissions:", error);
      alert("Failed to save permissions. Please try again.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleEditPermissionChange = (userId, permission, isChecked) => {
    setEditingPermissions(prev => {
      const current = prev[userId] || {};
      return {
        ...prev,
        [userId]: {
          ...current,
          [permission.toLowerCase() + '_access']: isChecked
        }
      };
    });
  };

  const handleUpdatePermission = async (userId) => {
    const updatedPermissions = editingPermissions[userId];
    
    if (!updatedPermissions) {
      alert("No changes to save");
      return;
    }

    // Validate that if write_access is true, read_access must also be true
    if (updatedPermissions.write_access && !updatedPermissions.read_access) {
      alert("Write access requires Read access. Please enable Read access.");
      return;
    }

    try {
      await projectService.updateUserPermission(
        instance,
        accounts[0],
        projectId,
        userId,
        updatedPermissions
      );

      alert("Permissions updated successfully!");
      
      // Clear editing state for this user
      setEditingPermissions(prev => {
        const updated = { ...prev };
        delete updated[userId];
        return updated;
      });

      // Refresh the user list
      await fetchProjectAndUsers();
    } catch (error) {
      console.error("Failed to update permissions:", error);
      alert("Failed to update permissions. Please try again.");
    }
  };

  const cancelEdit = (userId) => {
    setEditingPermissions(prev => {
      const updated = { ...prev };
      delete updated[userId];
      return updated;
    });
  };

  const startEditing = (userId, currentPermissions) => {
    setEditingPermissions(prev => ({
      ...prev,
      [userId]: {
        read_access: currentPermissions.read_access,
        write_access: currentPermissions.write_access
      }
    }));
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await fetchProjectAndUsers();
      // Clear any editing states
      setEditingPermissions({});
      setUserPermissions({});
    } catch (error) {
      console.error("Failed to refresh data:", error);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleUnassignUser = async (userId) => {
    setIsProcessing(true);
    
    try {
      // Set both permissions to false to unassign
      await projectService.updateUserPermission(
        instance,
        accounts[0],
        projectId,
        userId,
        {
          read_access: false,
          write_access: false
        }
      );
      
      alert("User unassigned successfully!");
      await fetchProjectAndUsers();
    } catch (error) {
      console.error("Failed to unassign user:", error);
      alert("Failed to unassign user. Please try again.");
    } finally {
      setIsProcessing(false);
    }
  };

  if (loadingProject) {
    return (
      <div style={{ padding: "20px", maxWidth: "1200px", margin: "0 auto", backgroundColor: "var(--bg-primary)", minHeight: "100vh" }}>
        <div style={{ textAlign: "center", padding: "40px" }}>
          <p style={{ color: "var(--text-secondary)" }}>Loading project...</p>
        </div>
      </div>
    );
  }

  if (error && !project) {
    return (
      <div style={{ padding: "20px", maxWidth: "1200px", margin: "0 auto", backgroundColor: "var(--bg-primary)", minHeight: "100vh" }}>
        <div style={{ padding: "20px" }}>
          <div
            style={{
              padding: "10px",
              backgroundColor: "var(--error-bg)",
              color: "var(--error-text)",
              border: "1px solid var(--color-falu-red)",
              borderRadius: "4px",
              marginBottom: "20px",
            }}
          >
            {error}
          </div>
          <Link to="/projects" style={{ textDecoration: "none", color: "var(--color-light-indigo)" }}>
            ← Back to Projects
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px", maxWidth: "1200px", margin: "0 auto", backgroundColor: "var(--bg-primary)", minHeight: "100vh" }}>
      <div
        style={{
          marginBottom: "20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <h1 style={{ color: "var(--text-primary)", marginBottom: "8px" }}>
            Assign Users to Project
          </h1>
          <p style={{ color: "var(--text-secondary)", margin: 0, fontSize: "18px", fontWeight: "500" }}>
            Project: {project?.name || "Loading..."}
          </p>
        </div>
        <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
          <button
            onClick={handleRefresh}
            disabled={isRefreshing || loadingUsers}
            style={{
              padding: "8px 16px",
              backgroundColor: "var(--color-light-blue)",
              color: "var(--color-dark-navy)",
              border: "none",
              borderRadius: "6px",
              cursor: isRefreshing || loadingUsers ? "not-allowed" : "pointer",
              fontSize: "14px",
              opacity: isRefreshing || loadingUsers ? 0.6 : 1,
              display: "flex",
              alignItems: "center",
              gap: "6px"
            }}
          >
            <span style={{ fontSize: "16px" }}>↻</span>
            {isRefreshing ? "Refreshing..." : "Refresh"}
          </button>
          <Link
            to="/projects"
            style={{ textDecoration: "none", color: "var(--color-light-indigo)", fontSize: "16px" }}
          >
            ← Back to Projects
          </Link>
        </div>
      </div>

      <div
        style={{
          backgroundColor: "var(--bg-secondary)",
          borderRadius: "8px",
          boxShadow: "var(--card-shadow)",
          border: "1px solid var(--border-color)"
        }}
      >
        <div style={{ padding: "20px", borderBottom: "1px solid var(--border-color)" }}>
          <h3 style={{ margin: 0, color: "var(--text-primary)" }}>
            Users ({availableUsers.length} total, {assignedUsers.length} assigned)
          </h3>
          <p style={{ margin: "8px 0 0 0", fontSize: "14px", color: "var(--text-secondary)" }}>
            Search and manage user access. Assigned users show current permissions.
          </p>
          
          {/* Search Input */}
          <div style={{ marginTop: "16px" }}>
            <input
              type="text"
              placeholder="Search by name or email..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: "100%",
                padding: "10px 16px",
                border: "1px solid var(--border-color)",
                borderRadius: "6px",
                fontSize: "14px",
                backgroundColor: "var(--bg-primary)",
                color: "var(--text-primary)",
                outline: "none",
                boxSizing: "border-box"
              }}
            />
          </div>
        </div>

        <div style={{ padding: "20px" }}>
          {loadingUsers && (
            <div style={{ textAlign: "center", padding: "20px" }}>
              <p style={{ color: "var(--text-secondary)" }}>Loading users...</p>
            </div>
          )}

          {!loadingUsers && filteredUsers.length === 0 && (
            <div style={{ textAlign: "center", padding: "20px" }}>
              <p style={{ color: "var(--text-secondary)" }}>
                {searchQuery ? "No users found matching your search" : "No users available"}
              </p>
            </div>
          )}

          {!loadingUsers && filteredUsers.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", backgroundColor: "var(--bg-secondary)" }}>
              <thead>
                <tr style={{ backgroundColor: "var(--bg-tertiary)" }}>
                  <th style={{ padding: "12px", textAlign: "left", borderBottom: "1px solid var(--border-color)", color: "var(--text-primary)" }}>
                    Name
                  </th>
                  <th style={{ padding: "12px", textAlign: "left", borderBottom: "1px solid var(--border-color)", color: "var(--text-primary)" }}>
                    Email
                  </th>
                  <th style={{ padding: "12px", textAlign: "left", borderBottom: "1px solid var(--border-color)", color: "var(--text-primary)" }}>
                    Read Access
                  </th>
                  <th style={{ padding: "12px", textAlign: "left", borderBottom: "1px solid var(--border-color)", color: "var(--text-primary)" }}>
                    Write Access
                  </th>
                  <th style={{ padding: "12px", textAlign: "left", borderBottom: "1px solid var(--border-color)", color: "var(--text-primary)" }}>
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map((user) => {
                  const isAssigned = isUserAssigned(user.id);
                  const assignedData = getAssignedUserPermissions(user.id);

                  return (
                    <tr 
                      key={user.id}
                      style={{ backgroundColor: hasActivePermissions(user.id) ? "var(--table-row-hover)" : "transparent" }}
                    >
                      <td style={{ padding: "12px", borderBottom: "1px solid var(--border-color)", color: "var(--text-primary)" }}>
                        {user.displayName || "N/A"}
                      </td>
                      <td style={{ padding: "12px", borderBottom: "1px solid var(--border-color)", color: "var(--text-primary)" }}>
                        {user.mail || user.userPrincipalName || "N/A"}
                      </td>
                      <td style={{ padding: "12px", borderBottom: "1px solid var(--border-color)" }}>
                        {hasActivePermissions(user.id) ? (
                          <span
                            style={{
                              padding: "4px 12px",
                              borderRadius: "12px",
                              fontSize: "12px",
                              fontWeight: "500",
                              backgroundColor: assignedData?.read_access ? "var(--success-bg)" : "var(--error-bg)",
                              color: assignedData?.read_access ? "var(--success-text)" : "var(--error-text)",
                            }}
                          >
                            {assignedData?.read_access ? "Yes" : "No"}
                          </span>
                        ) : (
                          <span style={{ fontSize: "13px", color: "rgba(255, 255, 255, 0.5)" }}>-</span>
                        )}
                      </td>
                      <td style={{ padding: "12px", borderBottom: "1px solid var(--border-color)" }}>
                        {hasActivePermissions(user.id) ? (
                          <span
                            style={{
                              padding: "4px 12px",
                              borderRadius: "12px",
                              fontSize: "12px",
                              fontWeight: "500",
                              backgroundColor: assignedData?.write_access ? "var(--success-bg)" : "var(--error-bg)",
                              color: assignedData?.write_access ? "var(--success-text)" : "var(--error-text)",
                            }}
                          >
                            {assignedData?.write_access ? "Yes" : "No"}
                          </span>
                        ) : (
                          <span style={{ fontSize: "13px", color: "rgba(255, 255, 255, 0.5)" }}>-</span>
                        )}
                      </td>
                      <td style={{ padding: "12px", borderBottom: "1px solid var(--border-color)" }}>
                        {hasActivePermissions(user.id) ? (
                          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                            <button
                              style={{
                                padding: "6px 12px",
                                backgroundColor: "var(--color-light-blue)",
                                color: "var(--color-dark-navy)",
                                border: "none",
                                borderRadius: "4px",
                                cursor: "pointer",
                                fontSize: "13px",
                                fontWeight: "500",
                                transition: "all 0.2s"
                              }}
                              onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                              onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                              onClick={() => openAssignModal(user)}
                            >
                              Edit
                            </button>
                            <button
                              style={{
                                padding: "6px 12px",
                                backgroundColor: "var(--color-falu-red)",
                                color: "var(--color-white)",
                                border: "none",
                                borderRadius: "4px",
                                cursor: isProcessing ? "not-allowed" : "pointer",
                                fontSize: "13px",
                                fontWeight: "500",
                                opacity: isProcessing ? 0.6 : 1,
                                transition: "all 0.2s"
                              }}
                              onMouseOver={(e) => !isProcessing && (e.currentTarget.style.opacity = "0.8")}
                              onMouseOut={(e) => !isProcessing && (e.currentTarget.style.opacity = "1")}
                              onClick={() => {
                                if (window.confirm(`Are you sure you want to unassign ${user.displayName || 'this user'} from the project?`)) {
                                  handleUnassignUser(user.id);
                                }
                              }}
                              disabled={isProcessing}
                            >
                              Unassign
                            </button>
                          </div>
                        ) : (
                          <button
                            style={{
                              padding: "6px 12px",
                              backgroundColor: "var(--color-btn-primary)",
                              color: "var(--color-white)",
                              border: "none",
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontSize: "13px",
                              fontWeight: "500",
                              transition: "all 0.2s"
                            }}
                            onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                            onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                            onClick={() => openAssignModal(user)}
                          >
                            Assign
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Assign/Edit Permissions Modal */}
      {isAssignModalOpen && selectedUser && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            backgroundColor: "var(--modal-overlay)",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            zIndex: 1000,
          }}
        >
          <div
            style={{
              backgroundColor: "var(--bg-secondary)",
              borderRadius: "8px",
              padding: "24px",
              maxWidth: "500px",
              width: "90%",
              border: "1px solid var(--border-color)"
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "20px",
              }}
            >
              <h2 style={{ color: "var(--text-primary)", margin: 0 }}>
                {isUserAssigned(selectedUser.id) ? "Edit Permissions" : "Assign User"}
              </h2>
              <button
                onClick={closeAssignModal}
                disabled={isProcessing}
                style={{
                  background: "none",
                  border: "none",
                  fontSize: "24px",
                  cursor: isProcessing ? "not-allowed" : "pointer",
                  color: "var(--text-secondary)",
                  padding: 0
                }}
              >
                ×
              </button>
            </div>

            <div style={{ marginBottom: "24px" }}>
              <div style={{ 
                padding: "12px", 
                backgroundColor: "var(--bg-primary)", 
                borderRadius: "6px",
                marginBottom: "20px"
              }}>
                <div style={{ fontSize: "14px", color: "var(--text-secondary)", marginBottom: "4px" }}>
                  User
                </div>
                <div style={{ fontSize: "16px", color: "var(--text-primary)", fontWeight: "500" }}>
                  {selectedUser.displayName || "N/A"}
                </div>
                <div style={{ fontSize: "13px", color: "rgba(255, 255, 255, 0.5)", marginTop: "2px" }}>
                  {selectedUser.mail || selectedUser.userPrincipalName || ""}
                </div>
              </div>

              <div style={{ fontSize: "14px", color: "var(--text-primary)", marginBottom: "12px", fontWeight: "500" }}>
                Select Permissions:
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    padding: "12px",
                    backgroundColor: "var(--bg-primary)",
                    borderRadius: "6px",
                    cursor: "pointer",
                    border: `2px solid ${modalPermissions.read_access ? "var(--color-brand-blue)" : "var(--border-color)"}`,
                    transition: "all 0.2s"
                  }}
                >
                  <input
                    type="checkbox"
                    checked={modalPermissions.read_access}
                    onChange={(e) => handleModalPermissionChange('read_access', e.target.checked)}
                    disabled={isProcessing}
                    style={{ marginRight: "12px", width: "18px", height: "18px", cursor: "pointer" }}
                  />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: "15px", color: "var(--text-primary)", fontWeight: "500" }}>
                      Read Access
                    </div>
                    <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px" }}>
                      View project data and reports
                    </div>
                  </div>
                </label>

                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    padding: "12px",
                    backgroundColor: "var(--bg-primary)",
                    borderRadius: "6px",
                    cursor: "pointer",
                    border: `2px solid ${modalPermissions.write_access ? "var(--color-brand-blue)" : "var(--border-color)"}`,
                    transition: "all 0.2s"
                  }}
                >
                  <input
                    type="checkbox"
                    checked={modalPermissions.write_access}
                    onChange={(e) => handleModalPermissionChange('write_access', e.target.checked)}
                    disabled={isProcessing}
                    style={{ marginRight: "12px", width: "18px", height: "18px", cursor: "pointer" }}
                  />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: "15px", color: "var(--text-primary)", fontWeight: "500" }}>
                      Write Access
                    </div>
                    <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px" }}>
                      Edit project data (includes Read access)
                    </div>
                  </div>
                </label>
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px" }}>
              <button
                onClick={closeAssignModal}
                disabled={isProcessing}
                style={{
                  padding: "10px 20px",
                  backgroundColor: "var(--color-battleship-gray)",
                  color: "var(--color-white)",
                  border: "none",
                  borderRadius: "6px",
                  cursor: isProcessing ? "not-allowed" : "pointer",
                  fontSize: "14px",
                  opacity: isProcessing ? 0.6 : 1
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleSavePermissions}
                disabled={isProcessing}
                style={{
                  padding: "10px 20px",
                  backgroundColor: "var(--color-btn-primary)",
                  color: "var(--color-white)",
                  border: "none",
                  borderRadius: "6px",
                  cursor: isProcessing ? "not-allowed" : "pointer",
                  fontSize: "14px",
                  opacity: isProcessing ? 0.6 : 1
                }}
              >
                {isProcessing ? "Saving..." : (isUserAssigned(selectedUser.id) ? "Update" : "Assign")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AssignUser;
