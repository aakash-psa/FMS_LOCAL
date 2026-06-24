import React, { useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Badge,
  makeStyles,
  Button,
  Checkbox,
  Input,
  Label,
  Dialog,
  DialogSurface,
  DialogTitle,
  DialogBody,
  DialogActions,
  DialogContent,
  Spinner,
  Card,
} from "@fluentui/react-components";
import { useAuth } from "../../msal/AuthProvider";
import Toast from "./Toast";
import SearchableDropdown from "./SearchableDropdown";
import ShareDialog from "./ShareDialog";
import OverwriteDialog from "./OverwriteDialog";
import SaveOptionsDialog from "./SaveOptionsDialog";
import {
  CheckmarkCircle24Regular,
  Edit24Regular,
  DataUsage24Regular,
  Calculator24Regular,
  ArrowLeft24Regular,
  Save24Regular,
  Folder24Regular,
  DocumentTableArrowRight24Regular,
  Building20Regular,
  Share24Regular,
} from "@fluentui/react-icons";
import { ensureTemplateSheetPresent } from "../utils/excelNamedRanges";

const useStyles = makeStyles({
  container: {
    background: "var(--bg-primary)",
    minHeight: "calc(100vh - 60px)",
  },
  content: {
    padding: "12px",
  },
  projectBanner: {
    marginBottom: "12px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "8px 10px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  projectInfo: {
    flex: 1,
    minWidth: 0,
  },
  projectName: {
    fontSize: "13px",
    fontWeight: "600",
    marginBottom: "2px",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  projectMeta: {
    fontSize: "10px",
    color: "var(--text-secondary)",
  },
  permissions: {
    display: "flex",
    gap: "6px",
  },
  badge: {
    background: "var(--success-bg)",
    color: "var(--success-text)",
    fontSize: "9px",
  },
  backButton: {
    marginBottom: "8px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
    fontSize: "12px",
  },
  section: {
    marginTop: "16px",
    marginBottom: "16px",
    background: "var(--bg-secondary)",
    padding: "12px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
  },
  sectionTitle: {
    fontSize: "13px",
    fontWeight: "600",
    marginBottom: "8px",
    color: "var(--text-primary)",
  },
  dropdown: {
    width: "100%",
    minWidth: "150px",
    fontSize: "11px",
    background: "#2b3331",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
    borderRadius: "6px",
    padding: "4px 36px 4px 12px",
    height: "30px",
    lineHeight: "20px",
    boxSizing: "border-box",
    outline: "none",
    colorScheme: "dark",
    appearance: "none",
    WebkitAppearance: "none",
    backgroundImage:
      "linear-gradient(45deg, transparent 50%, var(--text-secondary) 50%), linear-gradient(135deg, var(--text-secondary) 50%, transparent 50%)",
    backgroundPosition: "calc(100% - 16px) 12px, calc(100% - 11px) 12px",
    backgroundSize: "5px 5px, 5px 5px",
    backgroundRepeat: "no-repeat",
  },
  select: {
    width: "100%",
    minWidth: "150px",
    fontSize: "11px",
    background: "#2b3331",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
    borderRadius: "6px",
    padding: "4px 36px 4px 12px",
    height: "30px",
    lineHeight: "20px",
    boxSizing: "border-box",
    outline: "none",
    colorScheme: "dark",
    appearance: "none",
    WebkitAppearance: "none",
    backgroundImage:
      "linear-gradient(45deg, transparent 50%, var(--text-secondary) 50%), linear-gradient(135deg, var(--text-secondary) 50%, transparent 50%)",
    backgroundPosition: "calc(100% - 16px) 12px, calc(100% - 11px) 12px",
    backgroundSize: "5px 5px, 5px 5px",
    backgroundRepeat: "no-repeat",
  },
  actionButtons: {
    display: "flex",
    gap: "8px",
    marginTop: "12px",
    justifyContent: "flex-end",
  },
  saveButton: {
    background: "var(--accent-hover)",
    color: "white",
    fontSize: "12px",
  },
  emptyState: {
    textAlign: "center",
    padding: "30px 12px",
    color: "var(--text-secondary)",
  },
  emptyStateIcon: {
    fontSize: "40px",
    marginBottom: "8px",
    opacity: 0.3,
  },
  emptyStateText: {
    fontSize: "12px",
    marginBottom: "4px",
  },
  hospitalityBadge: {
    background: "var(--accent-hover)",
    color: "white",
    fontSize: "9px",
  },
  validationError: {
    color: "var(--error-text)",
    fontSize: "10px",
    marginTop: "6px",
  },
  loadingContainer: {
    textAlign: "center",
    padding: "30px 12px",
  },
  baseFileCard: {
    marginTop: "16px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "12px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
    cursor: "pointer",
    transition: "all 0.2s ease",
    "&:hover": {
      background: "var(--bg-tertiary)",
      transform: "translateY(-2px)",
    },
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  cardTitle: {
    fontSize: "12px",
    fontWeight: "600",
    flex: 1,
  },
  cardSubtitle: {
    fontSize: "10px",
    color: "var(--text-secondary)",
    marginTop: "4px",
  },
});

const AssetCoConsolidated = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const styles = useStyles();
  const project = location.state?.project;
  const { apiService } = useAuth();

  const [assets, setAssets] = useState([]);
  const [isLoadingAssets, setIsLoadingAssets] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);
  const [hasTemplateSheets, setHasTemplateSheets] = useState(false);
  const [isCalculating, setIsCalculating] = useState(false);
  const [selectedAssets, setSelectedAssets] = useState({}); // {assetId: scenarioId}
  const [isSaving, setIsSaving] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [saveOptionsDialogOpen, setSaveOptionsDialogOpen] = useState(false);
  const [saveAsDialogOpen, setSaveAsDialogOpen] = useState(false);
  const [selectScenarioForOverwriteOpen, setSelectScenarioForOverwriteOpen] = useState(false);
  const [consolidationName, setConsolidationName] = useState("");
  const [validationErrors, setValidationErrors] = useState([]);
  const [consolidatedScenarios, setConsolidatedScenarios] = useState([]); // For overwrite selection

  const [selectedScenarioForLoad, setSelectedScenarioForLoad] = useState("");
  const [shareDialogOpen, setShareDialogOpen] = useState(false);

  const [users, setUsers] = useState([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [isSharing, setIsSharing] = useState(false);
  const [isNormalising, setIsNormalising] = useState(false);
  const [selectedScenarioForShare, setSelectedScenarioForShare] = useState(null);

  useEffect(() => {
    const checkTemplateSheets = async () => {
      try {
        await Excel.run(async (context) => {
          const sheets = context.workbook.worksheets;
          sheets.load("items/name");
          await context.sync();

          const sheetNames = sheets.items.map((sheet) => sheet.name);
          const requiredTemplates = ["AC - CFS Template", "DC - CFS Template", "LC - CFS Template"];
          const allTemplatesExist = requiredTemplates.some((template) =>
            sheetNames.includes(template)
          );
          setHasTemplateSheets(allTemplatesExist);
        });
      } catch (error) {
        console.error("Failed to check template sheets:", error);
        setHasTemplateSheets(false);
      }
    };

    checkTemplateSheets();
  }, []);

  useEffect(() => {
    const fetchAssets = async () => {
      if (!project?.id) return;

      try {
        setIsLoadingAssets(true);
        const response = await apiService.fetchAllAssetScenarios(project.id);
        // Filter out assets that are deleted
        const activeAssets = (response.assets || []).filter((asset) => !asset.is_deleted);
        setAssets(activeAssets);
      } catch (error) {
        console.error("Failed to fetch assets:", error);
        showToast("Failed to load assets and scenarios", "error");
      } finally {
        setIsLoadingAssets(false);
      }
    };

    const fetchConsolidatedScenarios = async () => {
      if (!project?.id) return;

      try {
        const response = await apiService.fetchProjectScenarios(project.id, {
          iteration_type: "assetco_consolidation",
        });
        setConsolidatedScenarios(response.scenarios || []);
      } catch (error) {
        console.error("Failed to fetch consolidated scenarios:", error);
      }
    };

    fetchAssets();
    fetchConsolidatedScenarios();
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

  const isExcelWeb = () => Office.context.platform === Office.PlatformType.OfficeOnline;

  const handleLoadBaseFile = async () => {
    if (!project?.id) return;

    setIsDownloading(true);
    try {
      if (isExcelWeb()) {
        showToast("Please use Excel Desktop to import template.", "error");
        return;
      }

      const fileResponse = await apiService.downloadTemplate(project.id);
      if (!fileResponse || !fileResponse.file_base64) {
        showToast("No file data received from server", "error");
        return;
      }

      await Excel.run(async (context) => {
        const workbook = context.workbook;
        const worksheets = workbook.worksheets;
        worksheets.load("items/name");
        await context.sync();

        const tempSheet = worksheets.add("Temp");
        await context.sync();

        for (let index = worksheets.items.length - 1; index >= 0; index -= 1) {
          const sheet = worksheets.items[index];
          if (sheet.name !== "Temp") {
            sheet.delete();
          }
        }

        await context.sync();
        tempSheet.name = "Sheet1";
        await context.sync();

        workbook.insertWorksheetsFromBase64(fileResponse.file_base64, {
          sheetNamesToInsert: null,
          positionType: Excel.WorksheetPositionType.end,
        });
      });

      showToast("Template imported successfully!", "success");
      setHasTemplateSheets(true);
    } catch (error) {
      console.error("Failed to import template:", error);
      showToast("Failed to import template", "error");
    } finally {
      setIsDownloading(false);
    }
  };

  const handleAssetCheckboxChange = (assetId, checked) => {
    setSelectedAssets((prev) => {
      const updated = { ...prev };
      const assetKey = String(assetId);
      if (checked === true) {
        // Preserve existing selected scenario if present
        updated[assetKey] = updated[assetKey] ?? null;
      } else {
        delete updated[assetKey];
      }
      return updated;
    });
  };

  const handleScenarioDropdownChange = (assetId, scenarioId) => {
    setSelectedAssets((prev) => ({
      ...prev,
      [String(assetId)]: scenarioId,
    }));
  };

  const validateSelection = () => {
    const errors = [];

    if (Object.keys(selectedAssets).length === 0) {
      errors.push("Please select at least one asset for consolidation");
      return errors;
    }

    Object.entries(selectedAssets).forEach(([assetId, scenarioId]) => {
      if (!scenarioId) {
        const asset = assets.find((a) => a.id === parseInt(assetId));
        const assetName = asset?.asset_unique_identifier || `Asset ${assetId}`;
        errors.push(`Please select a scenario for ${assetName}`);
      }
    });

    return errors;
  };

  const handleSaveClick = () => {
    const errors = validateSelection();
    setValidationErrors(errors);

    if (errors.length === 0) {
      setSaveOptionsDialogOpen(true);
    }
  };

  const handleSaveAsNew = () => {
    setSaveOptionsDialogOpen(false);
    setSaveAsDialogOpen(true);
  };

  const handleSaveExisting = () => {
    setSaveOptionsDialogOpen(false);
    setSelectScenarioForOverwriteOpen(true);
  };

  const handleSaveAsNewConfirm = async () => {
    if (!consolidationName.trim()) {
      showToast("Please enter a name for the consolidated scenario", "error");
      return;
    }

    setSaveAsDialogOpen(false);
    setIsSaving(true);

    try {
      // Build selected_assets array
      const selected_assets = Object.entries(selectedAssets).map(([assetId, scenarioId]) => ({
        asset_id: parseInt(assetId),
        scenario_id: parseInt(scenarioId),
      }));

      const response = await apiService.saveIteration({
        project_id: project.id,
        name: consolidationName,
        iteration_type: "assetco_consolidation",
        selected_assets,
        input_json: { selected_assets },
      });
      if (response?.iteration_id) {
        // apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
        //   console.error("Failed to normalise scenario:", normaliseError);
        //   // showToast(normaliseError.message || "Failed to normalise scenario", "error");
        // });
      }

      showToast(`Consolidated scenario "${consolidationName}" saved successfully!`, "success");
      setConsolidationName("");
      setSelectedAssets({});
      setValidationErrors([]);
    } catch (error) {
      console.error("Failed to save consolidated scenario:", error);
      showToast(error.message || "Failed to save consolidated scenario", "error");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveAsCancel = () => {
    setSaveAsDialogOpen(false);
    setConsolidationName("");
  };

  const handleSaveOptionsCancel = () => {
    setSaveOptionsDialogOpen(false);
  };

  const handleConfirmOverwrite = async (scenario) => {
    setSelectScenarioForOverwriteOpen(false);
    setIsSaving(true);
    try {
      const selected_assets = Object.entries(selectedAssets).map(([assetId, scenarioId]) => ({
        asset_id: parseInt(assetId),
        scenario_id: parseInt(scenarioId),
      }));
      const response = await apiService.saveIteration({
        project_id: project.id,
        iteration_id: scenario.id,
        name: scenario.name,
        iteration_type: "assetco_consolidation",
        input_json: { selected_assets },
      });
      if (response?.iteration_id) {
        // apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
        //   console.error("Failed to normalise scenario:", normaliseError);
        //   // showToast(normaliseError.message || "Failed to normalise scenario", "error");
        // });
      }
      showToast(`Scenario "${scenario.name}" updated successfully!`, "success");
      setConsolidationName("");
      setSelectedAssets({});
      setValidationErrors([]);
    } catch (error) {
      console.error("Failed to overwrite scenario:", error);
      showToast(error.message || "Failed to overwrite scenario", "error");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSelectScenarioCancel = () => setSelectScenarioForOverwriteOpen(false);

  const handleShareScenario = async () => {
    if (consolidatedScenarios.length === 0) {
      showToast("No saved scenarios to share", "error");
      return;
    }
    setIsLoadingUsers(true);
    try {
      const response = await apiService.fetchUsersDetails();
      let usersList = [];
      if (Array.isArray(response)) usersList = response;
      else if (response?.users) usersList = response.users;
      else if (response?.data) usersList = response.data;
      setUsers(usersList);
    } catch (error) {
      showToast("Failed to load users list: " + error.message, "error");
      setUsers([]);
    } finally {
      setIsLoadingUsers(false);
    }
    setShareDialogOpen(true);
  };

  const handleShareConfirm = async (user, scenario) => {
    setIsSharing(true);
    setShareDialogOpen(false);
    try {
      await apiService.shareIteration({
        iteration_id: scenario.id,
        target_user_id: user.username,
      });
      showToast(`Scenario shared with ${user.username}!`, "success");
    } catch (error) {
      showToast(error.message || "Failed to share scenario", "error");
    } finally {
      setIsSharing(false);
      setSelectedScenarioForShare(null);
    }
  };

  const handleShareCancel = () => {
    setShareDialogOpen(false);
    setSelectedScenarioForShare(null);
  };

  const handleShareFromLoad = async () => {
    if (!selectedScenarioForLoad) return;
    const scenario = consolidatedScenarios.find(
      (s) => String(s.id) === String(selectedScenarioForLoad)
    );
    if (scenario) setSelectedScenarioForShare(scenario);
    setIsLoadingUsers(true);
    try {
      const response = await apiService.fetchUsersDetails();
      let usersList = [];
      if (Array.isArray(response)) usersList = response;
      else if (response?.users) usersList = response.users;
      else if (response?.data) usersList = response.data;
      setUsers(usersList);
    } catch (error) {
      showToast("Failed to load users: " + error.message, "error");
      setUsers([]);
    } finally {
      setIsLoadingUsers(false);
    }
    setShareDialogOpen(true);
  };

  const handleNormalise = async () => {
    if (!selectedScenarioForLoad) return;
    setIsNormalising(true);
    try {
      await apiService.normaliseIteration(parseInt(selectedScenarioForLoad, 10));
      showToast("Scenario normalised successfully!", "success");
    } catch (error) {
      showToast(error.message || "Failed to normalise scenario", "error");
    } finally {
      setIsNormalising(false);
    }
  };

  const handleSelectScenarioForLoad = (event, data) => {
    setSelectedScenarioForLoad(event.target.value || "");
  };

  const handleLoadScenarioConfirm = async () => {
    if (!selectedScenarioForLoad) {
      showToast("Please select a scenario to load", "error");
      return;
    }

    try {
      const response = await apiService.loadScenario(
        project.id,
        parseInt(selectedScenarioForLoad, 10)
      );
      const scenario = response?.scenario || response;
      const selected_assets = scenario?.input_json?.selected_assets || [];
      // const inputData = scenario?.input_json;
      const outputData = scenario?.output_json;

      const mapped = {};
      selected_assets.forEach((item) => {
        if (item?.asset_id && item?.scenario_id) {
          mapped[String(item.asset_id)] = parseInt(item.scenario_id, 10);
        }
      });

      setSelectedAssets(mapped);
      setValidationErrors([]);

      await Excel.run(async (context) => {
        context.application.calculationMode = Excel.CalculationMode.manual;
        await context.sync(); // commit manual mode before writes

        context.application.suspendApiCalculationUntilNextSync();
        context.application.suspendScreenUpdatingUntilNextSync();

        try {
          // if (Array.isArray(inputData) && inputData.length > 0) {
          //   const workbook = context.workbook;
          //   for (const item of inputData) {
          //     try {
          //       workbook.names.getItem(item.name).getRange().values = item.values;
          //     } catch (err) {
          //       console.error(`Failed to queue input for ${item.name}`, err);
          //     }
          //   }
          // }

          if (!outputData) {
            throw new Error("No output data found in scenario");
          }

          await processASSETCOOutputTemplate(context, outputData);
        } finally {
          context.application.calculationMode = Excel.CalculationMode.automatic;
          await context.sync();
        }
      });

      showToast(`Loaded scenario "${scenario?.name || ""}" successfully`, "success");
    } catch (error) {
      console.error("Failed to load scenario:", error);
      showToast(error.message || "Failed to load scenario", "error");
    }
  };
  const pasteDataframeToNamedRange = async (sheetName, namedRangeName, dataframeData) => {
    console.log(`Pasting dataframe to named range '${namedRangeName}' in sheet '${sheetName}'`);
    console.log(dataframeData);

    return await Excel.run(async (context) => {
      try {
        // Get the worksheet
        const sheet = context.workbook.worksheets.getItem(sheetName);
        console.log(`Found worksheet: '${sheetName}'`);
        // Try to get the named range from the sheet first
        let range;
        let foundInSheet = false;
        try {
          const namedRange = sheet.names.getItem(namedRangeName);
          console.log(`Found named range '${namedRangeName}' in sheet '${sheetName}'`);
          range = namedRange.getRange();
          range.load("address,rowCount,columnCount,worksheet/name");
          await context.sync();
          console.log("Resolved range:", {
            address: range.address,
            worksheet: range.worksheet?.name,
            rowCount: range.rowCount,
            columnCount: range.columnCount,
          });
          foundInSheet = true;
        } catch (sheetError) {
          try {
            const workbookNamedRange = context.workbook.names.getItem(namedRangeName);
            console.log(`Found named range '${namedRangeName}' in workbook`);
            range = workbookNamedRange.getRange();
            console.log(`Using named range '${range.address}' from workbook`);
          } catch (wbError) {
            // include underlying workbook error when rethrowing below
            throw new Error(
              `Named range '${namedRangeName}' not found in worksheet or workbook. Sheet error: ${sheetError?.message || sheetError}. Workbook error: ${wbError?.message || wbError}`
            );
          }
        }
        range.load("address,rowCount,columnCount,worksheet/name");
        await context.sync();
        range.values = dataframeData;
        await context.sync();
      } catch (error) {
        // Log full error to console and include original message/stack in the thrown error
        console.error(
          `pasteDataframeToNamedRange error for '${namedRangeName}' on sheet '${sheetName}':`,
          error
        );
        throw new Error(
          `Failed to paste into named range '${namedRangeName}' on sheet '${sheetName}'. Original error: ${error?.message || String(error)}${error?.stack ? `\nStack: ${error.stack}` : ""}`
        );
      }
    });
  };
  const processASSETCOOutputTemplate = async (context, outputs) => {
    const templateSheetName = "AC - CFS Template";
    const cashflowSheetName = "AC - CFS";

    const targetSheetName = cashflowSheetName;
    await ensureTemplateSheetPresent(context, templateSheetName, targetSheetName);

    console.log(outputs);

    const jobs = [];
    if (outputs.monthly_dfs) {
      for (const [, dfArr] of Object.entries(outputs.monthly_dfs)) {
        jobs.push({ namedRange: dfArr[0], dataframeData: dfArr[1].data });
      }
    }
    if (outputs.annual_dfs) {
      for (const [, dfArr] of Object.entries(outputs.annual_dfs)) {
        jobs.push({ namedRange: dfArr[0], dataframeData: dfArr[1].data });
      }
    }

    const workbook = context.workbook;
    const sheet = workbook.worksheets.getItem(targetSheetName);
    const resolved = jobs.map(({ namedRange, dataframeData }) => {
      const sheetItem = sheet.names.getItemOrNullObject(namedRange);
      const wbItem = workbook.names.getItemOrNullObject(namedRange);
      sheetItem.load("isNullObject");
      wbItem.load("isNullObject");
      return { namedRange, dataframeData, sheetItem, wbItem };
    });
    await context.sync();

    context.application.suspendApiCalculationUntilNextSync();
    context.application.suspendScreenUpdatingUntilNextSync();

    const writeErrors = [];
    for (const { namedRange, dataframeData, sheetItem, wbItem } of resolved) {
      if (!sheetItem.isNullObject) {
        sheetItem.getRange().values = dataframeData;
      } else if (!wbItem.isNullObject) {
        wbItem.getRange().values = dataframeData;
      } else {
        writeErrors.push(`Named range '${namedRange}' not found in sheet or workbook`);
      }
    }

    if (writeErrors.length) throw new Error(writeErrors.join("\n"));
  };

  const handleCalculations = async () => {
    const errors = validateSelection();
    if (errors.length > 0) {
      setValidationErrors(errors);
      showToast("Please complete asset/scenario selection before calculation", "error");
      return;
    }

    setIsCalculating(true);
    try {
      const selected_assets = Object.entries(selectedAssets).map(([assetId, scenarioId]) => ({
        asset_id: parseInt(assetId, 10),
        scenario_id: parseInt(scenarioId, 10),
      }));

      const response = await apiService.calculateConsolidated({
        calculation_module: "assetco_consolidation",
        project_id: project.id,
        selected_assets,
      });
      console.log("Received response from consolidation calculation:", response);

      await Excel.run(async (context) => {
        context.application.calculationMode = Excel.CalculationMode.manual;
        await context.sync(); // commit manual mode before writes

        context.application.suspendApiCalculationUntilNextSync();
        context.application.suspendScreenUpdatingUntilNextSync();

        try {
          await processASSETCOOutputTemplate(context, response.exceloutput);
        } finally {
          context.application.calculationMode = Excel.CalculationMode.automatic;
          await context.sync();
        }
      });

      showToast("AssetCo consolidated calculation completed successfully!", "success");
    } catch (error) {
      console.error("Failed to run AssetCo consolidated calculation:", error);
      showToast(error.message || "Failed to run AssetCo consolidated calculation", "error");
    } finally {
      setIsCalculating(false);
    }
  };

  const handleSaveConfirm = async () => {
    // Deprecated - replaced by handleSaveAsNewConfirm
    // Kept for backward compatibility
    handleSaveAsNewConfirm();
  };

  if (!project) {
    return (
      <div className={styles.container}>
        <div className={styles.content}>
          <h3>No Project Selected</h3>
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

      <SaveOptionsDialog
        open={saveOptionsDialogOpen}
        onClose={handleSaveOptionsCancel}
        onSaveExisting={handleSaveExisting}
        onSaveAsNew={handleSaveAsNew}
        hasSavedScenarios={consolidatedScenarios.length > 0}
      />

      {/* Save As New Dialog */}
      <Dialog open={saveAsDialogOpen} onOpenChange={(e, data) => setSaveAsDialogOpen(data.open)}>
        <DialogSurface style={{ background: "var(--bg-secondary)", color: "var(--text-primary)" }}>
          <DialogBody>
            <DialogTitle style={{ fontSize: "14px", color: "var(--text-primary)" }}>
              Save As New Scenario
            </DialogTitle>
            <DialogContent>
              <Label
                htmlFor="consolidation-name"
                style={{ fontSize: "12px", color: "var(--text-primary)" }}
              >
                Scenario Name
              </Label>
              <Input
                id="consolidation-name"
                value={consolidationName}
                onChange={(e) => setConsolidationName(e.target.value)}
                placeholder="Enter name..."
                size="small"
                style={{
                  width: "100%",
                  marginTop: "6px",
                  fontSize: "12px",
                  background: "var(--bg-tertiary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border-color)",
                }}
              />
            </DialogContent>
            <DialogActions>
              <Button size="small" appearance="secondary" onClick={handleSaveAsCancel}>
                Cancel
              </Button>
              <Button
                size="small"
                appearance="primary"
                onClick={handleSaveAsNewConfirm}
                disabled={!consolidationName.trim() || isSaving}
              >
                Save
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <OverwriteDialog
        open={selectScenarioForOverwriteOpen}
        onClose={handleSelectScenarioCancel}
        onConfirm={handleConfirmOverwrite}
        isSaving={isSaving}
        scenarios={consolidatedScenarios}
      />

      <div className={styles.content}>
        {/* Back Button */}

        {/* Project Banner */}
        <div className={styles.projectBanner}>
          <DataUsage24Regular style={{ fontSize: "16px" }} />
          <div className={styles.projectInfo}>
            <div className={styles.projectName}>{project.name} - AssetCo Consolidated</div>
            <div className={styles.projectMeta}>Consolidated Asset Calculations</div>
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

        <Card
          className={styles.baseFileCard}
          onClick={hasTemplateSheets || isDownloading ? undefined : handleLoadBaseFile}
          style={{
            opacity: hasTemplateSheets || isDownloading ? 0.5 : 1,
            cursor: hasTemplateSheets || isDownloading ? "not-allowed" : "pointer",
          }}
        >
          <div className={styles.cardHeader}>
            <Folder24Regular style={{ fontSize: "16px" }} />
            <div style={{ flex: 1 }}>
              <div className={styles.cardTitle}>
                {isDownloading
                  ? "Downloading..."
                  : hasTemplateSheets
                    ? "Base File Already Loaded"
                    : "Base File"}
              </div>
              <div className={styles.cardSubtitle}>
                {isDownloading
                  ? "Preparing template download..."
                  : hasTemplateSheets
                    ? "All template sheets are already in the workbook"
                    : "Download master template"}
              </div>
            </div>
            <DocumentTableArrowRight24Regular
              style={{ color: "var(--text-secondary)", fontSize: "16px" }}
            />
          </div>
        </Card>

        {/* Asset Selection Section */}
        {isLoadingAssets ? (
          <div className={styles.loadingContainer}>
            <Spinner size="small" />
            <div style={{ marginTop: "8px", fontSize: "11px", color: "var(--text-secondary)" }}>
              Loading assets...
            </div>
          </div>
        ) : assets.filter((a) => a.scenarios && a.scenarios.length > 0).length === 0 ? (
          <div className={styles.emptyState}>
            <div className={styles.emptyStateIcon}>
              <Building20Regular />
            </div>
            <div className={styles.emptyStateText}>No assets available</div>
            <div style={{ fontSize: "10px", opacity: 0.7 }}>
              Create assets and scenarios to use consolidation.
            </div>
          </div>
        ) : (
          <>
            <div className={styles.section}>
              <div className={styles.sectionTitle}>Load Saved Consolidation Scenario</div>
              <SearchableDropdown
                options={consolidatedScenarios.map((s) => ({ value: s.id, label: s.name }))}
                value={selectedScenarioForLoad}
                onChange={(val) => setSelectedScenarioForLoad(val ? String(val) : "")}
                placeholder="Choose a scenario to load"
                disabled={consolidatedScenarios.length === 0 || isSaving}
                style={{ marginBottom: "10px" }}
              />
              <div className={styles.actionButtons}>
                <Button
                  appearance="secondary"
                  size="small"
                  onClick={handleLoadScenarioConfirm}
                  disabled={!selectedScenarioForLoad || isSaving}
                >
                  Load Scenario
                </Button>
                <Button
                  appearance="secondary"
                  size="small"
                  onClick={handleShareFromLoad}
                  disabled={!selectedScenarioForLoad || isSaving}
                >
                  Share
                </Button>
                {/* <Button
                  appearance="secondary"
                  size="small"
                  onClick={handleNormalise}
                  disabled={!selectedScenarioForLoad || isSaving || isNormalising}
                >
                  {isNormalising ? "Normalising..." : "Normalise"}
                </Button> */}
              </div>
            </div>

            <div className={styles.section}>
              <div className={styles.sectionTitle}>Select Assets & Scenarios</div>
              <div
                style={{ fontSize: "11px", color: "var(--text-secondary)", marginBottom: "12px" }}
              >
                Choose assets and one scenario from each to consolidate.
              </div>

              <div style={{ maxHeight: "400px", overflowY: "auto" }}>
                {assets
                  .filter((a) => a.scenarios && a.scenarios.length > 0)
                  .map((asset) => {
                    const assetKey = String(asset.id);
                    const isSelected = Object.prototype.hasOwnProperty.call(
                      selectedAssets,
                      assetKey
                    );
                    const selectedScenarioId = selectedAssets[assetKey];
                    const selectedScenarioName =
                      asset.scenarios?.find((scenario) => scenario.id === selectedScenarioId)
                        ?.name || "";
                    const hasScenarios = asset.scenarios && asset.scenarios.length > 0;

                    return (
                      <div
                        key={asset.id}
                        style={{
                          background: "var(--bg-tertiary)",
                          padding: "8px",
                          marginBottom: "6px",
                          borderRadius: "4px",
                          border: isSelected
                            ? "1px solid var(--accent-hover)"
                            : "1px solid var(--border-color)",
                        }}
                      >
                        {/* Asset Header Row */}
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "6px",
                            marginBottom: isSelected ? "6px" : "0",
                          }}
                        >
                          <Checkbox
                            checked={isSelected}
                            onChange={(e, data) =>
                              handleAssetCheckboxChange(asset.id, data.checked)
                            }
                            disabled={!hasScenarios}
                          />
                          <Building20Regular
                            style={{ fontSize: "14px", color: "var(--accent-hover)" }}
                          />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div
                              style={{
                                fontSize: "11px",
                                fontWeight: "600",
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                              }}
                            >
                              {asset.asset_unique_identifier || "No ID"}
                              {asset.is_hospitality && (
                                <Badge
                                  className={styles.hospitalityBadge}
                                  size="small"
                                  style={{ marginLeft: "4px", fontSize: "9px" }}
                                >
                                  H
                                </Badge>
                              )}
                            </div>
                            <div
                              style={{
                                fontSize: "9px",
                                color: "var(--text-secondary)",
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                              }}
                            >
                              {asset.asset_name}
                            </div>
                          </div>
                          <Badge appearance="outline" size="small" style={{ fontSize: "9px" }}>
                            {hasScenarios ? asset.scenarios.length : 0}
                          </Badge>
                        </div>

                        {/* Scenario Dropdown (only shown when selected) */}
                        {isSelected && (
                          <div style={{ marginLeft: "26px" }}>
                            {hasScenarios ? (
                              <SearchableDropdown
                                options={asset.scenarios.map((s) => ({
                                  value: s.id,
                                  label: s.name,
                                }))}
                                value={selectedScenarioId ? String(selectedScenarioId) : ""}
                                onChange={(val) =>
                                  handleScenarioDropdownChange(asset.id, parseInt(val, 10))
                                }
                                placeholder="Select scenario..."
                                style={{ marginBottom: "0", fontSize: "11px" }}
                              />
                            ) : (
                              <span
                                style={{
                                  fontSize: "10px",
                                  color: "var(--text-secondary)",
                                  fontStyle: "italic",
                                }}
                              >
                                No scenarios available
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>

              {validationErrors.length > 0 && (
                <div className={styles.validationError}>
                  {validationErrors.map((error, index) => (
                    <div key={index}>• {error}</div>
                  ))}
                </div>
              )}

              <div className={styles.actionButtons}>
                <Button
                  appearance="secondary"
                  size="small"
                  icon={<Calculator24Regular />}
                  onClick={handleCalculations}
                  disabled={isCalculating || isSaving || Object.keys(selectedAssets).length === 0}
                >
                  {isCalculating ? "Calculating..." : "Run Calculations"}
                </Button>
                <Button
                  appearance="primary"
                  size="small"
                  icon={<Save24Regular />}
                  onClick={handleSaveClick}
                  disabled={
                    !hasWriteAccess ||
                    isSaving ||
                    isCalculating ||
                    Object.keys(selectedAssets).length === 0
                  }
                  className={styles.saveButton}
                >
                  {isSaving ? "Saving..." : "Save Consolidation"}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Share Dialog */}
      {/* Share Scenario Dialog */}
      <ShareDialog
        open={shareDialogOpen}
        onClose={handleShareCancel}
        onShare={handleShareConfirm}
        isSharing={isSharing}
        title="Share Consolidation Scenario"
        users={users}
        isLoadingUsers={isLoadingUsers}
        scenarios={consolidatedScenarios}
        initialScenario={selectedScenarioForShare}
      />
    </div>
  );
};

export default AssetCoConsolidated;
