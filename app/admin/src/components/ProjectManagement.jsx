import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import { projectService } from "../services/projectService";
import { userService } from "../services/userService";
import Icon from "./Icon";
import AssetManagement from "./AssetManagement";

const ProjectManagement = () => {
  const { instance, accounts } = useMsal();
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isRoshnMissing, setIsRoshnMissing] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState({});
  const [uploadingFiles, setUploadingFiles] = useState({});
  const [downloadingTemplates, setDownloadingTemplates] = useState({});
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedProject, setSelectedProject] = useState(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [isCreatingRoshn, setIsCreatingRoshn] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editingProject, setEditingProject] = useState(null);
  const [editProjectName, setEditProjectName] = useState("");
  const [isUpdating, setIsUpdating] = useState(false);
  const [availableUsers, setAvailableUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [pagination, setPagination] = useState({
    currentPage: 1,
    totalPages: 1,
    totalProjects: 0,
    limit: 10
  });
  const [isAssetManagementOpen, setIsAssetManagementOpen] = useState(false);
  const [selectedProjectForAssets, setSelectedProjectForAssets] = useState(null);

  useEffect(() => {
    fetchProjects();
  }, [instance, accounts]);

  const fetchProjects = async () => {
    try {
      setLoading(true);
      const response = await projectService.getAllProjects(
        instance,
        accounts[0]
      );
      
      // Handle both array response and paginated response
      const normalizeName = (project) => (project?.name || "").trim().toLowerCase();
      const projectsData = Array.isArray(response) ? response : (response.projects || response.data || []);
      const roshnProjects = projectsData.filter(
        (p) => normalizeName(p) === "roshn consolidation"
      );
      const isRoshnProjectMissing = roshnProjects.length === 0;
      setIsRoshnMissing(isRoshnProjectMissing);
      const otherProjects = projectsData.filter(
        (p) => normalizeName(p) !== "roshn consolidation"
      );
      const activeRoshnProject = roshnProjects.find((p) => !p.is_deleted);
      const roshnProject = activeRoshnProject || roshnProjects[0] || null;
      const sortedProjects = roshnProject
        ? [roshnProject, ...otherProjects]
        : projectsData;
      setProjects(sortedProjects);
      
      // Handle pagination if available
      if (response.pagination) {
        setPagination(prev => ({
          ...prev,
          totalPages: response.pagination.total_pages,
          totalProjects: response.pagination.total_projects
        }));
      } else if (Array.isArray(response)) {
        // If response is an array, set total to array length
        setPagination(prev => ({
          ...prev,
          totalPages: 1,
          totalProjects: response.length
        }));
      }
      
      setError(null);
    } catch (err) {
      console.error("Failed to fetch projects:", err);
      setError("Failed to load projects. Please try again.");
      setIsRoshnMissing(false);
    } finally {
      setLoading(false);
    }
  };

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= pagination.totalPages) {
      setPagination(prev => ({ ...prev, currentPage: newPage }));
    }
  };

  const handleFileUpload = async (event, projectId) => {
    const file = event.target.files[0];
    if (!file) return;

    // Validate file type
    const validExtensions = ['.xlsx', '.xls','.xlsm', '.xlsb'];
    const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    
    if (!validExtensions.includes(fileExtension)) {
      alert('Please upload only Excel files (.xlsx, .xls, .xlsm, .xlsb)');
      event.target.value = ''; // Reset file input
      return;
    }

    // // Validate file size (e.g., max 10MB)
    // const maxSize = 10 * 1024 * 1024; // 10MB in bytes
    // if (file.size > maxSize) {
    //   alert('File size should not exceed 10MB');
    //   event.target.value = '';
    //   return;
    // }

    setUploadingFiles(prev => ({ ...prev, [projectId]: true }));

    try {
      
      const result = await projectService.uploadTemplate(
        instance,
        accounts[0],
        projectId,
        file
      );

      alert(`Template "${file.name}" uploaded successfully!`);
      
      setUploadedFiles(prev => ({
        ...prev,
        [projectId]: file,
      }));

      // Refresh projects list to show the updated template link
      await fetchProjects();
    } catch (error) {
      alert(`Failed to upload template: ${error.message}`);
    } finally {
      setUploadingFiles(prev => ({ ...prev, [projectId]: false }));
      event.target.value = ''; // Reset file input
    }
  };

  const handleViewUsers = async (projectId) => {
    const project = projects.find((p) => p.id === projectId);
    setSelectedProject(project);
    setIsModalOpen(true);

    // Fetch users assigned to this project
    try {
      const projectUsers = await projectService.getProjectUsers(instance, accounts[0], projectId);
      // Update the selected project with fetched users
      setSelectedProject(prev => ({
        ...prev,
        users_details: projectUsers || []
      }));
    } catch (error) {
      console.error("Failed to load project users:", error);
      // Keep the modal open even if fetch fails
    }
  };

  const handleOpenAssetManagement = (projectId) => {
    const project = projects.find((p) => p.id === projectId);
    setSelectedProjectForAssets(project);
    setIsAssetManagementOpen(true);
  };

  const closeAssetManagement = () => {
    setIsAssetManagementOpen(false);
    setSelectedProjectForAssets(null);
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setSelectedProject(null);
  };

  const handleAssignMember = (projectId) => {
    const project = projects.find((p) => p.id === projectId);
    navigate(`/projects/${projectId}/assign-user`, { state: { project } });
  };

  const closeAssignModal = () => {
    setIsAssignModalOpen(false);
    setSelectedProject(null);
  };

  const handleCreateProject = async () => {
    if (!newProjectName.trim()) {
      alert("Please enter a project name");
      return;
    }

    const normalizedName = newProjectName.trim().toLowerCase();
    if (normalizedName === "roshn consolidation") {
      alert("This project name is reserved and cannot be created manually.");
      return;
    }

    setIsCreating(true);
    try {
      const projectData = {
        name: newProjectName.trim()
      };

      const result = await projectService.createProject(
        instance,
        accounts[0],
        projectData
      );
      alert("Project created successfully!");
      setNewProjectName("");
      setIsCreateModalOpen(false);

      // Refresh projects list
      await fetchProjects();
    } catch (error) {
      console.error("Failed to create project:", error);
      alert("Failed to create project. Please try again.");
    } finally {
      setIsCreating(false);
    }
  };

  const handleCreateRoshnConsolidation = async () => {
    setIsCreatingRoshn(true);
    try {
      const projectData = {
        name: "ROSHN Consolidation"
      };

      await projectService.createProject(
        instance,
        accounts[0],
        projectData
      );

      alert("ROSHN Consolidation created successfully!");
      setIsRoshnMissing(false);
      await fetchProjects();
    } catch (error) {
      console.error("Failed to create ROSHN Consolidation:", error);
      alert(error?.message || "Failed to create ROSHN Consolidation. Please try again.");
    } finally {
      setIsCreatingRoshn(false);
    }
  };

  const handleEditProject = (project) => {
    setEditingProject(project);
    setEditProjectName(project.name);
    setIsEditModalOpen(true);
  };

  const closeEditModal = () => {
    setIsEditModalOpen(false);
    setEditingProject(null);
    setEditProjectName("");
  };

  const handleUpdateProject = async () => {
    if (!editProjectName.trim()) {
      alert("Please enter a project name");
      return;
    }

    setIsUpdating(true);
    try {
      const projectData = {
        name: editProjectName.trim()
      };

      const result = await projectService.updateProject(
        instance,
        accounts[0],
        editingProject.id,
        projectData
      );
      alert("Project updated successfully!");
      closeEditModal();

      // Refresh projects list
      await fetchProjects();
    } catch (error) {
      console.error("Failed to update project:", error);
      alert("Failed to update project. Please try again.");
    } finally {
      setIsUpdating(false);
    }
  };

  const openCreateModal = () => {
    setIsCreateModalOpen(true);
  };

  const closeCreateModal = () => {
    setIsCreateModalOpen(false);
    setNewProjectName("");
  };

  const handleDeactivateProject = async (project) => {
    if (!window.confirm(`Are you sure you want to deactivate the project "${project.name}"?`)) {
      return;
    }

    try {
      await projectService.deactivateProject(
        instance,
        accounts[0],
        project.id
      );

      alert("Project deactivated successfully!");
      
      // Refresh projects list
      await fetchProjects();
    } catch (error) {
      console.error("Failed to deactivate project:", error);
      alert("Failed to deactivate project. Please try again.");
    }
  };

  const handleActivateProject = async (project) => {
    if (!window.confirm(`Are you sure you want to activate the project "${project.name}"?`)) {
      return;
    }

    try {
      await projectService.activateProject(
        instance,
        accounts[0],
        project.id
      );

      alert("Project activated successfully!");
      
      // Refresh projects list
      await fetchProjects();
    } catch (error) {
      console.error("Failed to activate project:", error);
      alert("Failed to activate project. Please try again.");
    }
  };

  const handleViewTemplate = async (project) => {
    const projectId = project.id;
    const templatePath = project.template_link || project.template_file_link;

    if (!templatePath) {
      alert('No template available for this project');
      return;
    }

    setDownloadingTemplates(prev => ({ ...prev, [projectId]: true }));

    try {
      // Get the decoded file data from the API
      const { url, filename } = await projectService.getTemplateDownloadUrl(
        instance,
        accounts[0],
        projectId,
      );

      // Create a temporary anchor element to trigger download
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      // Clean up the object URL after download
      setTimeout(() => {
        window.URL.revokeObjectURL(url);
      }, 100);
    } catch (error) {
      console.error('Failed to download template:', error);
      alert(`Failed to download template: ${error.message}`);
    } finally {
      setDownloadingTemplates(prev => ({ ...prev, [projectId]: false }));
    }
  };

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
        <h1 style={{ color: "var(--text-primary)", display: "flex", alignItems: "center", gap: "12px" }}>
          <Icon icon="material-symbols:folder-open-outline" size={32} />
          Project Management
        </h1>
        <Link
          to="/dashboard"
          style={{ textDecoration: "none", color: "var(--color-light-indigo)", display: "flex", alignItems: "center", gap: "6px" }}
        >
          <Icon icon="material-symbols:arrow-back-outline" size={20} />
          Back to Dashboard
        </Link>
      </div>

      <div style={{ marginBottom: "20px", display: "flex", gap: "10px" }}>
        <button
          onClick={openCreateModal}
          style={{
            padding: "10px 20px",
            backgroundColor: "var(--color-btn-primary)",
            color: "var(--color-white)",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "16px",
            display: "flex",
            alignItems: "center",
            gap: "8px"
          }}
        >
          <Icon icon="material-symbols:add-circle-outline" size={20} />
          Create New Project
        </button>
        <button
          onClick={fetchProjects}
          style={{
            padding: "10px 20px",
            backgroundColor: "var(--color-light-blue)",
            color: "var(--color-dark-navy)",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "16px",
            display: "flex",
            alignItems: "center",
            gap: "8px"
          }}
          disabled={loading}
        >
          <Icon icon="material-symbols:refresh-outline" size={20} />
          {loading ? "Refreshing..." : "Refresh Projects"}
        </button>
      </div>

      <div
        style={{
          backgroundColor: "var(--bg-secondary)",
          borderRadius: "8px",
          boxShadow: "0 2px 4px rgba(0,0,0,0.3)",
          border: "1px solid var(--border-color)"
        }}
      >
        <div style={{ padding: "20px", borderBottom: "1px solid var(--border-color)" }}>
          <h3 style={{ margin: 0, color: "var(--text-primary)" }}>
            Projects Overview ({pagination.totalProjects} projects)
          </h3>
        </div>

        <div style={{ padding: "20px" }}>
          {loading && (
            <div style={{ textAlign: "center", padding: "20px" }}>
              <p style={{ color: "var(--text-secondary)" }}>Loading projects...</p>
            </div>
          )}

          {error && (
            <div
              style={{
                padding: "10px",
                backgroundColor: "rgba(124, 30, 30, 0.2)",
                color: "var(--color-tea-rose)",
                border: "1px solid var(--color-falu-red)",
                borderRadius: "4px",
                marginBottom: "20px",
              }}
            >
              {error}
            </div>
          )}

          {!loading && !error && (
            <table style={{ width: "100%", borderCollapse: "collapse", backgroundColor: "var(--bg-secondary)" }}>
              <thead>
                <tr style={{ backgroundColor: "var(--bg-tertiary)" }}>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid var(--border-color)",
                      color: "var(--text-primary)",
                      width: "60px"
                    }}
                  >
                    #
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid var(--border-color)",
                      color: "var(--text-primary)"
                    }}
                  >
                    Project Name
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid var(--border-color)",
                      color: "var(--text-primary)"
                    }}
                  >
                    Users Count
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid var(--border-color)",
                      color: "var(--text-primary)"
                    }}
                  >
                    Template
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid var(--border-color)",
                      color: "var(--text-primary)"
                    }}
                  >
                    Created At
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid var(--border-color)",
                      color: "var(--text-primary)"
                    }}
                  >
                    Status
                  </th>
                  <th
                    style={{
                      padding: "12px",
                      textAlign: "left",
                      borderBottom: "1px solid var(--border-color)",
                      color: "var(--text-primary)"
                    }}
                  >
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {isRoshnMissing && (
                  <tr style={{ backgroundColor: "rgba(36, 26, 1, 0.95)" }}>
                    <td colSpan={7} style={{ padding: "16px" }}>
                      <div style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: "16px",
                        flexWrap: "wrap"
                      }}>
                        <div>
                          <div style={{ fontWeight: 600, color: "var(--text-primary)", marginBottom: "6px" }}>
                            ROSHN Consolidation is missing from projects.
                          </div>
                          <div style={{ color: "var(--text-secondary)", fontSize: "14px" }}>
                            The project list did not return a ROSHN Consolidation entry. Please click the button to create it.
                          </div>
                        </div>
                        <button
                          onClick={handleCreateRoshnConsolidation}
                          disabled={isCreatingRoshn}
                          style={{
                            padding: "10px 18px",
                            backgroundColor: isCreatingRoshn ? "var(--color-battleship-gray)" : "var(--color-light-blue)",
                            color: isCreatingRoshn ? "var(--color-white)" : "var(--color-dark-navy)",
                            border: "none",
                            borderRadius: "4px",
                            cursor: isCreatingRoshn ? "not-allowed" : "pointer",
                            fontSize: "14px",
                            fontWeight: 600,
                            opacity: isCreatingRoshn ? 0.7 : 1
                          }}
                        >
                          {isCreatingRoshn ? "Creating..." : "Create Roshn Consolidation"}
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
                {projects.map((project, index) => {
                  const isRoshnProject = (project?.name || "").trim().toLowerCase() === "roshn consolidation";
                  return (
                    <tr
                      key={project.id}
                      style={{
                        backgroundColor: isRoshnProject ? "rgba(40, 136, 238, 0.08)" : "transparent",
                      }}
                    >
                      <td
                        style={{
                          padding: "12px",
                          borderBottom: "1px solid var(--border-color)",
                          color: "var(--text-secondary)",
                          fontWeight: "500"
                        }}
                      >
                      {(pagination.currentPage - 1) * pagination.limit + index + 1}
                    </td>
                    <td
                      style={{
                        padding: "12px",
                        borderBottom: "1px solid var(--border-color)",
                        color: "var(--text-primary)"
                      }}
                    >
                      {project.name}
                    </td>
                    <td
                      style={{
                        padding: "12px",
                        borderBottom: "1px solid var(--border-color)",
                        color: "var(--text-primary)"
                      }}
                    >
                      {project.user_count || project.users_count || 0}
                    </td>
                    <td
                      style={{
                        padding: "12px",
                        borderBottom: "1px solid var(--border-color)",
                      }}
                    >
                      {project.template_link || project.template_file_link ? (
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <button
                            onClick={() => handleViewTemplate(project)}
                            disabled={downloadingTemplates[project.id]}
                            style={{
                              padding: "4px 8px",
                              backgroundColor: downloadingTemplates[project.id] ? "var(--color-battleship-gray)" : "transparent",
                              color: downloadingTemplates[project.id] ? "var(--color-white)" : "var(--color-brand-blue)",
                              border: downloadingTemplates[project.id] ? "none" : "1px solid var(--color-brand-blue)",
                              borderRadius: "4px",
                              cursor: downloadingTemplates[project.id] ? "not-allowed" : "pointer",
                              fontSize: "12px",
                              opacity: downloadingTemplates[project.id] ? 0.6 : 1,
                              display: "flex",
                              alignItems: "center",
                              gap: "4px"
                            }}
                          >
                            <Icon icon={downloadingTemplates[project.id] ? "material-symbols:hourglass-empty-outline" : "material-symbols:check-circle-outline"} size={16} />
                            {downloadingTemplates[project.id] ? "Loading..." : "View Template"}
                          </button>
                          <div style={{ position: "relative" }}>
                            <input
                              type="file"
                              accept=".xlsx,.xls,.xlsm,.xlsb"
                              onChange={(e) => handleFileUpload(e, project.id)}
                              disabled={uploadingFiles[project.id]}
                              style={{
                                position: "absolute",
                                top: 0,
                                left: 0,
                                width: "100%",
                                height: "100%",
                                opacity: 0,
                                cursor: uploadingFiles[project.id] ? "not-allowed" : "pointer",
                              }}
                              id={`excel-replace-${project.id}`}
                            />
                            <button
                              disabled={uploadingFiles[project.id]}
                              style={{
                                padding: "4px 8px",
                                backgroundColor: uploadingFiles[project.id] ? "var(--color-battleship-gray)" : "var(--color-wisteria)",
                                color: "var(--color-white)",
                                border: "none",
                                borderRadius: "4px",
                                cursor: uploadingFiles[project.id] ? "not-allowed" : "pointer",
                                fontSize: "11px",
                                opacity: uploadingFiles[project.id] ? 0.6 : 1,
                                fontWeight: "500"
                              }}
                            >
                              {uploadingFiles[project.id] ? "⏳ Replacing..." : "🔄 Replace"}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div style={{ position: "relative" }}>
                          <input
                            type="file"
                            accept=".xlsx,.xls,.xlsm,.xlsb"
                            onChange={(e) => handleFileUpload(e, project.id)}
                            disabled={uploadingFiles[project.id]}
                            style={{
                              position: "absolute",
                              top: 0,
                              left: 0,
                              width: "100%",
                              height: "100%",
                              opacity: 0,
                              cursor: uploadingFiles[project.id] ? "not-allowed" : "pointer",
                            }}
                            id={`excel-upload-${project.id}`}
                          />
                          <button
                            disabled={uploadingFiles[project.id]}
                            style={{
                              padding: "4px 8px",
                              backgroundColor: uploadingFiles[project.id] ? "var(--color-battleship-gray)" : "var(--color-light-blue)",
                              color: uploadingFiles[project.id] ? "var(--color-white)" : "var(--color-dark-navy)",
                              border: "none",
                              borderRadius: "4px",
                              cursor: uploadingFiles[project.id] ? "not-allowed" : "pointer",
                              fontSize: "12px",
                              opacity: uploadingFiles[project.id] ? 0.6 : 1,
                            }}
                          >
                            {uploadingFiles[project.id] ? "📤 Uploading..." : "📄 Upload"}
                          </button>
                        </div>
                      )}
                    </td>
                    <td
                      style={{
                        padding: "12px",
                        borderBottom: "1px solid var(--border-color)",
                        color: "var(--text-primary)"
                      }}
                    >
                      {new Date(project.created_at).toLocaleDateString()}
                    </td>
                    <td
                      style={{
                        padding: "12px",
                        borderBottom: "1px solid var(--border-color)",
                      }}
                    >
                      <span
                        style={{
                          padding: "4px 12px",
                          borderRadius: "12px",
                          fontSize: "12px",
                          fontWeight: "500",
                          backgroundColor: project.is_deleted
                            ? "rgba(124, 30, 30, 0.2)"
                            : "rgba(140, 170, 238, 0.1)",
                          color: project.is_deleted ? "var(--color-tea-rose)" : "var(--color-light-indigo)",
                        }}
                      >
                        {project.is_deleted ? "Inactive" : "Active"}
                      </span>
                    </td>
                    <td
                      style={{
                        padding: "12px",
                        borderBottom: "1px solid var(--border-color)",
                      }}
                    >
                      {(project?.name || "").trim().toLowerCase() === "roshn consolidation" ? (
                        <>
                          <button
                            onClick={() => handleViewUsers(project.id)}
                            style={{
                              margin: "4px 8px 4px 0",
                              padding: "8px 14px",
                              fontSize: "12px",
                              border: "none",
                              backgroundColor: "var(--color-btn-primary)",
                              color: "var(--color-white)",
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontWeight: "500",
                              transition: "all 0.2s"
                            }}
                            onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                            onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                          >
                            View Users
                          </button>

                          <button
                            onClick={() => handleAssignMember(project.id)}
                            style={{
                              margin: "4px 8px 4px 0",
                              padding: "8px 14px",
                              fontSize: "12px",
                              border: "none",
                              backgroundColor: "var(--color-wisteria)",
                              color: "var(--color-white)",
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontWeight: "500",
                              transition: "all 0.2s"
                            }}
                            onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                            onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                          >
                            Assign user
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => handleEditProject(project)}
                            style={{
                              margin: "4px 8px 4px 0",
                              padding: "8px 14px",
                              fontSize: "12px",
                              border: "none",
                              backgroundColor: "var(--color-light-blue)",
                              color: "var(--color-dark-navy)",
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontWeight: "500",
                              transition: "all 0.2s"
                            }}
                            onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                            onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                          >
                            Edit
                          </button>

                          <button
                            onClick={() => handleViewUsers(project.id)}
                            style={{
                              margin: "4px 8px 4px 0",
                              padding: "8px 14px",
                              fontSize: "12px",
                              border: "none",
                              backgroundColor: "var(--color-btn-primary)",
                              color: "var(--color-white)",
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontWeight: "500",
                              transition: "all 0.2s"
                            }}
                            onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                            onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                          >
                            View Users
                          </button>

                          <button
                            onClick={() => handleAssignMember(project.id)}
                            style={{
                              margin: "4px 8px 4px 0",
                              padding: "8px 14px",
                              fontSize: "12px",
                              border: "none",
                              backgroundColor: "var(--color-wisteria)",
                              color: "var(--color-white)",
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontWeight: "500",
                              transition: "all 0.2s"
                            }}
                            onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                            onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                          >
                            Assign user
                          </button>

                          <button
                            onClick={() => handleOpenAssetManagement(project.id)}
                            style={{
                              margin: "4px 8px 4px 0",
                              padding: "8px 14px",
                              fontSize: "12px",
                              border: "none",
                              backgroundColor: "var(--color-btn-primary)",
                              color: "var(--color-white)",
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontWeight: "500",
                              transition: "all 0.2s"
                            }}
                            onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                            onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                          >
                            Assets
                          </button>

                          {project.is_deleted ? (
                            <button
                              onClick={() => handleActivateProject(project)}
                              style={{
                                margin: "4px 8px 4px 0",
                                padding: "8px 14px",
                                fontSize: "12px",
                                border: "none",
                                backgroundColor: "var(--color-btn-primary)",
                                color: "var(--color-white)",
                                borderRadius: "4px",
                                cursor: "pointer",
                                fontWeight: "500",
                                transition: "all 0.2s"
                              }}
                              onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                              onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                            >
                              Activate
                            </button>
                          ) : (
                            <button
                              onClick={() => handleDeactivateProject(project)}
                              style={{
                                margin: "4px 8px 4px 0",
                                padding: "8px 14px",
                                fontSize: "12px",
                                border: "none",
                                backgroundColor: "var(--color-falu-red)",
                                color: "var(--color-white)",
                                borderRadius: "4px",
                                cursor: "pointer",
                                fontWeight: "500",
                                transition: "all 0.2s"
                              }}
                              onMouseOver={(e) => e.currentTarget.style.opacity = "0.8"}
                              onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                            >
                              Deactivate
                            </button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                )})}
              </tbody>
            </table>
          )}

          {!loading && !error && projects.length === 0 && (
            <div style={{ textAlign: "center", padding: "20px" }}>
              <p style={{ color: "var(--text-secondary)" }}>No projects found. Create your first project!</p>
            </div>
          )}

          {/* Pagination Controls */}
          {!loading && !error && pagination.totalPages > 1 && (
            <div style={{ 
              marginTop: "20px", 
              display: "flex", 
              justifyContent: "center", 
              alignItems: "center",
              gap: "10px"
            }}>
              <button
                onClick={() => handlePageChange(pagination.currentPage - 1)}
                disabled={pagination.currentPage === 1}
                style={{
                  padding: "8px 16px",
                  backgroundColor: pagination.currentPage === 1 ? "var(--color-battleship-gray)" : "var(--color-light-blue)",
                  color: pagination.currentPage === 1 ? "var(--text-secondary)" : "var(--color-dark-navy)",
                  border: "none",
                  borderRadius: "4px",
                  cursor: pagination.currentPage === 1 ? "not-allowed" : "pointer",
                  fontSize: "14px"
                }}
              >
                Previous
              </button>
              
              <span style={{ fontSize: "14px", color: "var(--text-secondary)" }}>
                Page {pagination.currentPage} of {pagination.totalPages}
              </span>
              
              <button
                onClick={() => handlePageChange(pagination.currentPage + 1)}
                disabled={pagination.currentPage === pagination.totalPages}
                style={{
                  padding: "8px 16px",
                  backgroundColor: pagination.currentPage === pagination.totalPages ? "var(--color-battleship-gray)" : "var(--color-light-blue)",
                  color: pagination.currentPage === pagination.totalPages ? "var(--text-secondary)" : "var(--color-dark-navy)",
                  border: "none",
                  borderRadius: "4px",
                  cursor: pagination.currentPage === pagination.totalPages ? "not-allowed" : "pointer",
                  fontSize: "14px"
                }}
              >
                Next
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Modal */}
      {isModalOpen && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            backgroundColor: "rgba(35, 38, 52, 0.88)",
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
              padding: "20px",
              maxWidth: "600px",
              width: "90%",
              maxHeight: "80vh",
              overflowY: "auto",
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
              <h2 style={{ color: "var(--text-primary)" }}>
                {selectedProject?.name} - Team Users (
                {selectedProject?.user_count || selectedProject?.users_count || 0})
              </h2>
              <button
                onClick={closeModal}
                style={{
                  background: "none",
                  border: "none",
                  fontSize: "24px",
                  cursor: "pointer",
                  color: "var(--text-secondary)",
                  display: "flex",
                  alignItems: "center"
                }}
              >
                <Icon icon="material-symbols:close-outline" size={24} />
              </button>
            </div>

            <div style={{ marginBottom: "20px" }}>
              {selectedProject?.users_details &&
              selectedProject.users_details.length > 0 ? (
                <table style={{ width: "100%", borderCollapse: "collapse", backgroundColor: "var(--bg-secondary)" }}>
                  <thead>
                    <tr style={{ backgroundColor: "var(--bg-primary)" }}>
                      <th
                        style={{
                          padding: "12px",
                          textAlign: "left",
                          borderBottom: "1px solid var(--border-color)",
                          color: "var(--text-primary)"
                        }}
                      >
                        Name
                      </th>
                      <th
                        style={{
                          padding: "12px",
                          textAlign: "left",
                          borderBottom: "1px solid var(--border-color)",
                          color: "var(--text-primary)"
                        }}
                      >
                        Email
                      </th>
                      <th
                        style={{
                          padding: "12px",
                          textAlign: "left",
                          borderBottom: "1px solid var(--border-color)",
                          color: "var(--text-primary)"
                        }}
                      >
                        Read Access
                      </th>
                      <th
                        style={{
                          padding: "12px",
                          textAlign: "left",
                          borderBottom: "1px solid var(--border-color)",
                          color: "var(--text-primary)"
                        }}
                      >
                        Write Access
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedProject.users_details.map((member) => (
                      <tr key={member.id}>
                        <td
                          style={{
                            padding: "12px",
                            borderBottom: "1px solid var(--border-color)",
                            color: "var(--text-primary)"
                          }}
                        >
                          {member.user?.first_name && member.user?.last_name 
                            ? `${member.user.first_name} ${member.user.last_name}`
                            : member.user?.username || "N/A"}
                        </td>
                        <td
                          style={{
                            padding: "12px",
                            borderBottom: "1px solid var(--border-color)",
                            color: "var(--text-primary)"
                          }}
                        >
                          {member.user?.email || "N/A"}
                        </td>
                        <td
                          style={{
                            padding: "12px",
                            borderBottom: "1px solid var(--border-color)",
                            color: "var(--text-primary)"
                          }}
                        >
                          <span
                            style={{
                              padding: "4px 8px",
                              borderRadius: "4px",
                              fontSize: "12px",
                              backgroundColor: member.read_access
                                ? "rgba(140, 170, 238, 0.1)"
                                : "rgba(124, 30, 30, 0.2)",
                              color: member.read_access ? "var(--color-light-indigo)" : "var(--color-tea-rose)",
                            }}
                          >
                            {member.read_access ? "Yes" : "No"}
                          </span>
                        </td>
                        <td
                          style={{
                            padding: "12px",
                            borderBottom: "1px solid var(--border-color)",
                            color: "var(--text-primary)"
                          }}
                        >
                          <span
                            style={{
                              padding: "4px 8px",
                              borderRadius: "4px",
                              fontSize: "12px",
                              backgroundColor: member.write_access
                                ? "rgba(140, 170, 238, 0.1)"
                                : "rgba(124, 30, 30, 0.2)",
                              color: member.write_access ? "var(--color-light-indigo)" : "var(--color-tea-rose)",
                            }}
                          >
                            {member.write_access ? "Yes" : "No"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ textAlign: "center", padding: "20px" }}>
                  <p style={{ color: "var(--text-secondary)" }}>No users assigned to this project yet.</p>
                </div>
              )}
            </div>

            <div style={{ textAlign: "right" }}>
              <button
                onClick={closeModal}
                style={{
                  padding: "8px 16px",
                  backgroundColor: "var(--color-battleship-gray)",
                  color: "var(--color-white)",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Project Modal */}
      {isCreateModalOpen && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            backgroundColor: "rgba(35, 38, 52, 0.88)",
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
              padding: "20px",
              maxWidth: "400px",
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
              <h2 style={{ color: "var(--text-primary)" }}>Create New Project</h2>
              <button
                onClick={closeCreateModal}
                style={{
                  background: "none",
                  border: "none",
                  fontSize: "24px",
                  cursor: "pointer",
                  color: "var(--text-secondary)",
                }}
              >
                ×
              </button>
            </div>

            <div style={{ marginBottom: "20px" }}>
              <label
                style={{
                  display: "block",
                  marginBottom: "8px",
                  fontWeight: "bold",
                  color: "var(--text-primary)"
                }}
              >
                Project Name:
              </label>
              <input
                type="text"
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                placeholder="Enter project name"
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  fontSize: "14px",
                  backgroundColor: "var(--bg-primary)",
                  color: "var(--text-primary)",
                  boxSizing: "border-box"
                }}
                disabled={isCreating}
              />
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: "10px",
              }}
            >
              <button
                onClick={closeCreateModal}
                style={{
                  padding: "8px 16px",
                  backgroundColor: "var(--color-battleship-gray)",
                  color: "var(--color-white)",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                }}
                disabled={isCreating}
              >
                Cancel
              </button>
              <button
                onClick={handleCreateProject}
                style={{
                  padding: "8px 16px",
                  backgroundColor: "var(--color-btn-primary)",
                  color: "var(--color-white)",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  opacity: isCreating ? 0.6 : 1,
                }}
                disabled={isCreating}
              >
                {isCreating ? "Creating..." : "Create Project"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Project Modal */}
      {isEditModalOpen && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            backgroundColor: "rgba(35, 38, 52, 0.88)",
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
              padding: "20px",
              maxWidth: "400px",
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
              <h2 style={{ color: "var(--text-primary)" }}>Edit Project</h2>
              <button
                onClick={closeEditModal}
                style={{
                  background: "none",
                  border: "none",
                  fontSize: "24px",
                  cursor: "pointer",
                  color: "var(--text-secondary)",
                }}
              >
                ×
              </button>
            </div>

            <div style={{ marginBottom: "20px" }}>
              <label
                style={{
                  display: "block",
                  marginBottom: "8px",
                  fontWeight: "bold",
                  color: "var(--text-primary)"
                }}
              >
                Project Name:
              </label>
              <input
                type="text"
                value={editProjectName}
                onChange={(e) => setEditProjectName(e.target.value)}
                placeholder="Enter project name"
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  fontSize: "14px",
                  backgroundColor: "var(--bg-primary)",
                  color: "var(--text-primary)",
                  boxSizing: "border-box"
                }}
                disabled={isUpdating}
              />
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: "10px",
              }}
            >
              <button
                onClick={closeEditModal}
                style={{
                  padding: "8px 16px",
                  backgroundColor: "var(--color-battleship-gray)",
                  color: "var(--color-white)",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                }}
                disabled={isUpdating}
              >
                Cancel
              </button>
              <button
                onClick={handleUpdateProject}
                style={{
                  padding: "8px 16px",
                  backgroundColor: "var(--color-light-blue)",
                  color: "var(--color-dark-navy)",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  opacity: isUpdating ? 0.6 : 1,
                }}
                disabled={isUpdating}
              >
                {isUpdating ? "Updating..." : "Update Project"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Asset Management Modal */}
      {isAssetManagementOpen && selectedProjectForAssets && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            backgroundColor: "rgba(35, 38, 52, 0.88)",
            display: "flex",
            justifyContent: "center",
            alignItems: "flex-start",
            zIndex: 9999,
            overflowY: "auto",
            padding: "20px 0"
          }}
        >
          <div
            style={{
              backgroundColor: "var(--bg-secondary)",
              borderRadius: "8px",
              maxWidth: "1200px",
              width: "95%",
              border: "1px solid var(--border-color)",
              margin: "20px auto",
              position: "relative",
              zIndex: 10000
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "16px",
                borderBottom: "1px solid var(--border-color)",
                position: "sticky",
                top: 0,
                backgroundColor: "var(--bg-secondary)",
                zIndex: 100,
                borderRadius: "8px 8px 0 0"
              }}
            >
              <h2 style={{ color: "var(--text-primary)", margin: 0 }}>
                Asset Management
              </h2>
              <button
                onClick={closeAssetManagement}
                style={{
                  background: "none",
                  border: "none",
                  fontSize: "24px",
                  cursor: "pointer",
                  color: "var(--text-secondary)",
                  display: "flex",
                  alignItems: "center",
                  padding: "4px",
                  zIndex: 101
                }}
              >
                <Icon icon="material-symbols:close-outline" size={24} />
              </button>
            </div>
            <div style={{ padding: "16px" }}>
              <AssetManagement
                projectId={selectedProjectForAssets.id}
                projectName={selectedProjectForAssets.name}
              />
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                padding: "16px",
                borderTop: "1px solid var(--border-color)",
                backgroundColor: "var(--bg-primary)",
                borderRadius: "0 0 8px 8px"
              }}
            >
              <button
                onClick={closeAssetManagement}
                style={{
                  padding: "8px 16px",
                  backgroundColor: "var(--color-battleship-gray)",
                  color: "var(--color-white)",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "14px",
                  fontWeight: "500"
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectManagement;
