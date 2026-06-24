import React, { useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Badge,
  makeStyles,
  Button,
  Dialog,
  DialogSurface,
  DialogTitle,
  DialogBody,
  DialogActions,
  DialogContent,
  Input,
  Label,
  Spinner,
} from "@fluentui/react-components";
import { useAuth } from "../../msal/AuthProvider";
import Toast from "./Toast";
import {
  CheckmarkCircle24Regular,
  Edit24Regular,
  Building20Regular,
  ArrowLeft24Regular,
  ChevronRight16Regular,
} from "@fluentui/react-icons";

const useStyles = makeStyles({
  container: {
    background: "var(--bg-primary)",
    minHeight: "calc(100vh - 60px)",
  },
  content: {
    padding: "12px",
    maxWidth: "100%",
    margin: "0 auto",
    boxSizing: "border-box",
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
    width: "100%",
    boxSizing: "border-box",
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
    marginBottom: "12px",
    paddingLeft: "4px",
  },
  backButton: {
    marginBottom: "12px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
  },
  assetsGrid: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    marginTop: "12px",
    width: "100%",
    boxSizing: "border-box",
  },
  assetCard: {
    background: "var(--bg-secondary)",
    padding: "10px 12px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
    transition: "all 0.15s ease",
    cursor: "pointer",
    width: "100%",
    boxSizing: "border-box",
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
  assetCardBody: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    flex: 1,
    minWidth: 0,
  },
  assetCardHeader: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    flex: 1,
    minWidth: 0,
  },
  assetCardChevron: {
    color: "var(--text-secondary)",
    fontSize: "16px",
    flexShrink: 0,
  },
  assetIcon: {
    fontSize: "20px",
    color: "var(--accent-hover)",
    flexShrink: 0,
  },
  assetInfo: {
    flex: 1,
    minWidth: 0,
  },
  assetName: {
    fontSize: "13px",
    fontWeight: "600",
    color: "var(--text-primary)",
    marginBottom: "2px",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  assetIdentifier: {
    fontSize: "11px",
    color: "var(--text-secondary)",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  hospitalityBadge: {
    background: "var(--accent-hover)",
    color: "white",
    fontSize: "10px",
    marginLeft: "8px",
  },
  assetActions: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  actionButton: {
    width: "100%",
    justifyContent: "flex-start",
  },
  downloadButton: {
    background: "var(--accent-hover)",
    color: "white",
    "&:hover": {
      background: "var(--accent-primary)",
    },
  },
  calculateButton: {
    background: "var(--success-bg)",
    color: "var(--success-text)",
    border: "1px solid var(--success-bg)",
  },
  saveButton: {
    background: "var(--bg-tertiary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
  },
  scenariosButton: {
    background: "var(--bg-tertiary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
  },
  emptyState: {
    textAlign: "center",
    padding: "40px 20px",
    color: "var(--text-secondary)",
  },
  emptyStateIcon: {
    fontSize: "48px",
    marginBottom: "12px",
    opacity: 0.3,
  },
  emptyStateText: {
    fontSize: "13px",
    marginBottom: "6px",
  },
  dropdownSection: {
    marginBottom: "20px",
  },
  dropdownLabel: {
    color: "var(--text-primary)",
    fontSize: "14px",
    fontWeight: "500",
    marginBottom: "8px",
    display: "block",
  },
  dropdown: {
    width: "100%",
    marginBottom: "12px",
    backgroundColor: "var(--bg-secondary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
  },
  loadButton: {
    width: "100%",
    background: "var(--accent-hover)",
    color: "var(--text-primary)",
    border: "none",
  },
  actionsGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "12px",
    marginTop: "24px",
  },
  actionCard: {
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "20px 16px",
    borderRadius: "8px",
    border: "1px solid var(--border-color)",
    cursor: "pointer",
    transition: "all 0.2s ease",
    textAlign: "center",
    "&:hover": {
      background: "var(--bg-tertiary)",
      transform: "translateY(-2px)",
    },
  },
  actionCardDisabled: {
    background: "var(--bg-secondary)",
    color: "var(--text-secondary)",
    padding: "20px 16px",
    borderRadius: "8px",
    border: "1px solid var(--border-color)",
    cursor: "not-allowed",
    textAlign: "center",
    opacity: 0.5,
  },
  actionIcon: {
    fontSize: "32px",
    marginBottom: "12px",
  },
  actionTitle: {
    fontSize: "14px",
    fontWeight: "600",
    marginBottom: "4px",
  },
  actionDescription: {
    fontSize: "11px",
    color: "var(--text-secondary)",
  },
});

const AssetCoScenarios = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const styles = useStyles();
  const project = location.state?.project;
  const { apiService } = useAuth();

  const [assets, setAssets] = useState([]);
  const [isLoadingAssets, setIsLoadingAssets] = useState(true);
  const [assetLoadingStates, setAssetLoadingStates] = useState({}); // {assetId: {downloading: bool, calculating: bool, saving: bool}}
  const [toasts, setToasts] = useState([]);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [scenarioName, setScenarioName] = useState("");
  const [currentAssetForSave, setCurrentAssetForSave] = useState(null);

  useEffect(() => {
    const fetchAssets = async () => {
      if (!project?.id) return;

      try {
        setIsLoadingAssets(true);
        const response = await apiService.fetchProjectAssets(project.id);
        setAssets(response.assets || []);
      } catch (error) {
        console.error("Failed to fetch assets:", error);
        showToast("Failed to load assets", "error");
      } finally {
        setIsLoadingAssets(false);
      }
    };

    fetchAssets();
  }, [project?.id]);

  const showToast = (message, type = "success") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      removeToast(id);
    }, 5000);
  };

  const removeToast = (id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  };

  const setAssetLoading = (assetId, loadingType, value) => {
    setAssetLoadingStates((prev) => ({
      ...prev,
      [assetId]: {
        ...(prev[assetId] || {}),
        [loadingType]: value,
      },
    }));
  };

  const handleViewScenarios = async (asset) => {
    navigate(`/assetco/${asset.id}`, {
      state: {
        project,
        asset,
        is_hospitality: !!asset?.is_hospitality,
      },
    });
  };

  if (!project) {
    return (
      <div className={styles.container}>
        <div className={styles.content}>
          <h3 className={styles.header}>No Project Selected</h3>
          <Button icon={<ArrowLeft24Regular />} onClick={() => navigate("/")}>
            Back to Projects
          </Button>
        </div>
      </div>
    );
  }

  const hasWriteAccess = project.permissions?.write_access;

  return (
    <div className={styles.container}>
      {/* Toast Container */}
      <div
        style={{
          position: "fixed",
          top: "20px",
          right: "20px",
          zIndex: 10000,
          display: "flex",
          flexDirection: "column",
          gap: "12px",
          maxWidth: "400px",
        }}
      >
        {toasts.map((toast) => (
          <Toast
            key={toast.id}
            message={toast.message}
            type={toast.type}
            onClose={() => removeToast(toast.id)}
          />
        ))}
      </div>

      <div className={styles.content}>
        <div className={styles.projectBanner}>
          <Building20Regular />
          <div className={styles.projectInfo}>
            <div className={styles.projectName}>{project.name} - AssetCo</div>
            <div className={styles.projectMeta}>Asset-based Calculations</div>
          </div>
          <div className={styles.permissions}>
            {project.permissions?.read_access && (
              <Badge className={styles.badge} size="small" icon={<CheckmarkCircle24Regular />}>
                Read
              </Badge>
            )}
            {hasWriteAccess && (
              <Badge className={styles.badge} size="small" icon={<Edit24Regular />}>
                Write
              </Badge>
            )}
          </div>
        </div>

        {/* Assets Grid */}
        {isLoadingAssets ? (
          <div
            style={{ textAlign: "center", padding: "40px 20px", color: "var(--text-secondary)" }}
          >
            <Spinner size="medium" />
            <div style={{ marginTop: "12px", fontSize: "12px" }}>Loading assets...</div>
          </div>
        ) : assets.length === 0 ? (
          <div className={styles.emptyState}>
            <div className={styles.emptyStateIcon}>
              <Building20Regular />
            </div>
            <div className={styles.emptyStateText}>No assets available</div>
            <div style={{ fontSize: "11px", opacity: 0.7 }}>
              Please create assets in the admin panel to start working with AssetCo calculations.
            </div>
          </div>
        ) : (
          <div className={styles.assetsGrid}>
            {assets
              .filter((asset) => !asset.is_deleted)
              .map((asset) => {
                const loadingState = assetLoadingStates[asset.id] || {};
                const isDownloading = loadingState.downloading || false;
                const isCalculating = loadingState.calculating || false;
                const isSaving = loadingState.saving || false;
                const isAnyLoading = isDownloading || isCalculating || isSaving;

                return (
                  <div
                    key={asset.id}
                    className={styles.assetCard}
                    onClick={() => handleViewScenarios(asset)}
                  >
                    <Building20Regular className={styles.assetIcon} />
                    <div className={styles.assetInfo}>
                      <div className={styles.assetName}>
                        {asset.asset_unique_identifier || "No identifier"}
                        {asset.is_hospitality && (
                          <Badge className={styles.hospitalityBadge} size="small">
                            Hospitality
                          </Badge>
                        )}
                      </div>
                      <div className={styles.assetIdentifier}>{asset.asset_name}</div>
                    </div>
                    <ChevronRight16Regular className={styles.assetCardChevron} />
                  </div>
                );
              })}
          </div>
        )}
      </div>
    </div>
  );
};

export default AssetCoScenarios;
