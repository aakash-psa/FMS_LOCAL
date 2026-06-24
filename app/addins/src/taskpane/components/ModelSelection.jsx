import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Badge, makeStyles } from "@fluentui/react-components";
import {
  Folder24Regular,
  CheckmarkCircle24Regular,
  Edit24Regular,
  Calculator20Regular,
  Building20Regular,
  DataUsage20Regular,
  DocumentTableArrowRight20Regular,
  ChevronRight16Regular,
} from "@fluentui/react-icons";

const useStyles = makeStyles({
  container: {
    background: "var(--bg-primary)",
    minHeight: "calc(100vh - 60px)",
  },
  content: {
    padding: "12px",
  },
  projectBanner: {
    marginBottom: "16px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "8px 12px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  projectInfo: {
    flex: 1,
  },
  projectName: {
    fontSize: "13px",
    fontWeight: "600",
    marginBottom: "2px",
  },
  projectMeta: {
    fontSize: "11px",
    color: "var(--text-secondary)",
  },
  permissions: {
    display: "flex",
    gap: "4px",
  },
  badge: {
    background: "var(--success-bg)",
    color: "var(--success-text)",
    fontSize: "10px",
  },
  header: {
    color: "var(--text-primary)",
    fontSize: "13px",
    fontWeight: "600",
    marginBottom: "8px",
    paddingLeft: "4px",
  },
  modelList: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
  },
  modelItem: {
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "10px 12px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
    cursor: "pointer",
    transition: "all 0.15s ease",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    "&:hover": {
      background: "var(--bg-tertiary)",
      boxShadow: "0 1px 3px rgba(0, 0, 0, 0.1)",
    },
    "&:active": {
      transform: "scale(0.98)",
    },
  },
  modelIcon: {
    fontSize: "20px",
    color: "var(--accent-hover)",
    flexShrink: 0,
  },
  modelContent: {
    flex: 1,
    minWidth: 0,
  },
  modelTitle: {
    fontSize: "13px",
    fontWeight: "600",
    marginBottom: "2px",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  modelDescription: {
    fontSize: "11px",
    color: "var(--text-secondary)",
    lineHeight: "1.3",
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical",
    overflow: "hidden",
  },
  chevron: {
    fontSize: "16px",
    color: "var(--text-secondary)",
    flexShrink: 0,
  },
});

const ModelSelection = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const styles = useStyles();
  const project = location.state?.project;

  if (!project) {
    navigate("/");
    return null;
  }

  const handleModelSelect = (modelType) => {
    let route = "/scenarios"; // default for landco_devco
    
    switch (modelType) {
      case "landco_devco":
        route = "/scenarios";
        break;
      case "assetco":
        route = "/assetco";
        break;
      case "assetco_consolidated":
        route = "/assetco-consolidated";
        break;
      case "jv_consolidation":
        route = "/jv-consolidation";
        break;
      case "consolidation":
        route = "/consolidation";
        break;
      default:
        route = "/scenarios";
    }

    navigate(route, { state: { project, modelType } });
  };

  return (
    <div className={styles.container}>
      <div className={styles.content}>
        {/* Project Banner */}
        <div className={styles.projectBanner}>
          <Folder24Regular />
          <div className={styles.projectInfo}>
            <div className={styles.projectName}>{project.name}</div>
            <div className={styles.projectMeta}>Select Model Type</div>
          </div>
          <div className={styles.permissions}>
            {project.permissions?.read_access && (
              <Badge className={styles.badge} size="small" icon={<CheckmarkCircle24Regular />}>
                Read
              </Badge>
            )}
            {project.permissions?.write_access && (
              <Badge className={styles.badge} size="small" icon={<Edit24Regular />}>
                Write
              </Badge>
            )}
          </div>
        </div>

        <h3 className={styles.header}>Choose Model Type</h3>

        <div className={styles.modelList}>
          {/* LandCo/DevCo */}
          <div
            className={styles.modelItem}
            onClick={() => handleModelSelect("landco_devco")}
          >
            <Calculator20Regular className={styles.modelIcon} />
            <div className={styles.modelContent}>
              <div className={styles.modelTitle}>LandCo & DevCo</div>
              <div className={styles.modelDescription}>
                Land and Development Company calculations
              </div>
            </div>
            <ChevronRight16Regular className={styles.chevron} />
          </div>

          {/* AssetCo */}
          <div
            className={styles.modelItem}
            onClick={() => handleModelSelect("assetco")}
          >
            <Building20Regular className={styles.modelIcon} />
            <div className={styles.modelContent}>
              <div className={styles.modelTitle}>AssetCo</div>
              <div className={styles.modelDescription}>
                Asset-based calculations for individual assets
              </div>
            </div>
            <ChevronRight16Regular className={styles.chevron} />
          </div>

          {/* AssetCo Consolidated */}
          <div
            className={styles.modelItem}
            onClick={() => handleModelSelect("assetco_consolidated")}
          >
            <DataUsage20Regular className={styles.modelIcon} />
            <div className={styles.modelContent}>
              <div className={styles.modelTitle}>AssetCo Consolidated</div>
              <div className={styles.modelDescription}>
                Consolidated view of all asset calculations
              </div>
            </div>
            <ChevronRight16Regular className={styles.chevron} />
          </div>

          {/* Consolidation */}
          <div
            className={styles.modelItem}
            onClick={() => handleModelSelect("jv_consolidation")}
          >
            <DocumentTableArrowRight20Regular className={styles.modelIcon} />
            <div className={styles.modelContent}>
              <div className={styles.modelTitle}>JV Consolidation</div>
              <div className={styles.modelDescription}>
                Consolidate selected JV scenarios before full project consolidation
              </div>
            </div>
            <ChevronRight16Regular className={styles.chevron} />
          </div>

          {/* Consolidation */}
          <div
            className={styles.modelItem}
            onClick={() => handleModelSelect("consolidation")}
          >
            <DocumentTableArrowRight20Regular className={styles.modelIcon} />
            <div className={styles.modelContent}>
              <div className={styles.modelTitle}>Project Consolidation</div>
              <div className={styles.modelDescription}>
                Complete project consolidation across all models
              </div>
            </div>
            <ChevronRight16Regular className={styles.chevron} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default ModelSelection;
