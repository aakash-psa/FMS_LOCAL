import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../msal/AuthProvider";
import { Spinner, Card, Badge, makeStyles, Button } from "@fluentui/react-components";
import { 
  Folder24Regular, 
  CheckmarkCircle24Regular, 
  Edit24Regular, 
  ArrowClockwise24Regular,
  DataUsage24Regular
} from "@fluentui/react-icons";

const useStyles = makeStyles({
  container: {
    background: "var(--bg-primary)",
    minHeight: "calc(100vh - 60px)",
    width: "100%",
    boxSizing: "border-box",
    overflowX: "hidden",
    overflowY: "auto",
    scrollbarWidth: "none",
    msOverflowStyle: "none",
    scrollbarColor: "transparent transparent",
    "&::-webkit-scrollbar": { width: 0, height: 0 },
    "&::-webkit-scrollbar-thumb": { background: "transparent" },
    "&::-webkit-scrollbar-track": { background: "transparent" },
  },
  content: {
    padding: "20px",
    width: "100%",
    boxSizing: "border-box",
    overflowY: "auto",
    scrollbarWidth: "none",
    msOverflowStyle: "none",
    scrollbarColor: "transparent transparent",
    "&::-webkit-scrollbar": { width: 0, height: 0 },
    "&::-webkit-scrollbar-thumb": { background: "transparent" },
    "&::-webkit-scrollbar-track": { background: "transparent" },
  },
  headerSection: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "20px",
  },
  header: {
    color: "var(--text-primary)",
    fontSize: "20px",
    fontWeight: "400",
    margin: 0,
  },
  refreshButton: {
    background: "var(--bg-tertiary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
    "&:hover": {
      background: "var(--accent-hover)",
    },
  },
  userInfo: {
    color: "var(--text-secondary)",
    fontSize: "14px",
    marginBottom: "24px",
    lineHeight: "1.6",
  },
  loading: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    minHeight: "200px",
  },
  error: {
    color: "var(--error-text)",
    padding: "16px",
    background: "var(--error-bg)",
    borderRadius: "8px",
    border: "1px solid var(--error-color)",
    marginBottom: "16px",
  },
  projectCard: {
    marginBottom: "16px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "16px",
    borderRadius: "8px",
    border: "1px solid var(--border-color)",
    cursor: "pointer",
    transition: "all 0.2s ease",
    "&:hover": {
      background: "var(--bg-tertiary)",
      transform: "translateY(-2px)",
      boxShadow: "var(--card-shadow)",
    },
  },
  projectHeader: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    marginBottom: "12px",
  },
  projectName: {
    fontSize: "16px",
    fontWeight: "600",
    flex: 1,
  },
  projectDetails: {
    fontSize: "13px",
    color: "var(--text-secondary)",
    marginBottom: "8px",
  },
  projectMeta: {
    fontSize: "12px",
    color: "var(--text-secondary)",
    marginTop: "8px",
  },
  permissions: {
    display: "flex",
    gap: "8px",
    marginTop: "12px",
  },
  badge: {
    background: "var(--success-bg)",
    color: "var(--success-text)",
  },
  roshnCard: {
    marginBottom: "16px",
    background: "#021a0d",
    color: "#cfefd1",
    transition: "all 0.2s ease",
    padding: "18px 20px",
    borderRadius: "12px",
    border: "1px solid #01412a",
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    minHeight: "92px",
    "&:hover": {
      background: "#033024",
      transform: "translateY(-2px)",
      boxShadow: "0 12px 28px rgba(0, 0, 0, 0.16)",
    },
  },
  noProjects: {
    color: "var(--text-secondary)",
    textAlign: "center",
    padding: "40px",
    fontSize: "14px",
  },
});

const ProjectList = () => {
  const navigate = useNavigate();
  const { getUserProjects } = useAuth();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [userInfo, setUserInfo] = useState(null);
  const styles = useStyles();

  const fetchProjects = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getUserProjects();
      
      const accessibleProjects = (data.projects || []).filter(
        (project) => project.permissions?.read_access || project.permissions?.write_access
      );

      setProjects(accessibleProjects);
      setUserInfo({
        name: data.user_name,
        email: data.user_email,
        userId: data.user_id,
        total: data.total_projects,
      });
    } catch (err) {
      setError(err.message || "Failed to load projects");
      console.error("Error fetching projects:", err);
    } finally {
      setLoading(false);
    }
  }, [getUserProjects]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const handleRefresh = () => {
    fetchProjects();
  };

  const handleProjectClick = (project) => {
    navigate("/model-selection", { state: { project } });
  };

  const formatDate = (dateString) => {
    if (!dateString) return "N/A";
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.content}>
          <div className={styles.loading}>
            <Spinner size="large" label="Loading projects..." />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.content}>
        <div className={styles.headerSection}>
          <h3 className={styles.header}>My Projects</h3>
          <Button
            className={styles.refreshButton}
            icon={<ArrowClockwise24Regular />}
            onClick={handleRefresh}
            disabled={loading}
          >
            Refresh
          </Button>
        </div>

        {error && <div className={styles.error}>{error}</div>}

        {projects.length === 0 ? (
          <div className={styles.noProjects}>No projects assigned</div>
        ) : (
          <>
            {(() => {
              const roshnProject = projects.find((p) =>
                p.name?.toLowerCase().includes("roshn consolidation")
              );
              if (!roshnProject) {
                return null;
              }

              return (
                <Card
                  key="roshn-consolidation"
                  className={`${styles.roshnCard}`}
                  onClick={() =>
                    navigate("/roshn-consolidated", { state: { project: roshnProject } })
                  }
                >
                      <div className={styles.projectHeader}>
                    <DataUsage24Regular style={{ fontSize: "18px", color: "#8be3a9" }} />
                    <div>
                      <div className={styles.projectName}>ROSHN Consolidation</div>
                      <div className={styles.projectMeta} style={{ color: "#d7f8d4", fontSize: "12px", marginTop: "4px" }}>
                        Open ROSHN consolidation workspace
                      </div>
                    </div>
                  </div>
                </Card>
              );
            })()}

            {projects
              .filter((p) => !p.name?.toLowerCase().includes("roshn consolidation"))
              .map((project) => (
              <Card
                key={project.id}
                className={styles.projectCard}
                onClick={() => handleProjectClick(project)}
              >
                <div className={styles.projectHeader}>
                  <Folder24Regular />
                  <div className={styles.projectName}>{project.name}</div>
                </div>

                {/* {project.template_link && (
                  <div className={styles.projectDetails}>
                    Template: {project.template_link}
                  </div>
                )} */}
                <div className={styles.permissions}>
                  {project.permissions?.read_access && (
                    <Badge className={styles.badge} icon={<CheckmarkCircle24Regular />}>
                      Read Access
                    </Badge>
                  )}
                  {project.permissions?.write_access && (
                    <Badge className={styles.badge} icon={<Edit24Regular />}>
                      Write Access
                    </Badge>
                  )}
                </div>
              </Card>
            ))}
          </>
        )}
      </div>
    </div>
  );
};

export default ProjectList;
