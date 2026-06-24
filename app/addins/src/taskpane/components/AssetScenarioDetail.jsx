import React, { useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Card,
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
import SearchableDropdown from "./SearchableDropdown";
import ShareDialog from "./ShareDialog";
import OverwriteDialog from "./OverwriteDialog";
import SaveOptionsDialog from "./SaveOptionsDialog";
import {
  CheckmarkCircle24Regular,
  Edit24Regular,
  Building24Regular,
  Calculator24Regular,
  Save24Regular,
  Open24Regular,
  ArrowLeft24Regular,
  ArrowDownload24Regular,
  Share24Regular,
  ArrowSync24Regular,
} from "@fluentui/react-icons";
import { readNamedRangesByPrefixes, buildNamedItemCache, ensureTemplateSheetPresent } from "../utils/excelNamedRanges";

const useStyles = makeStyles({
  container: {
    background: "var(--bg-primary)",
    minHeight: "calc(100vh - 60px)",
  },
  content: {
    padding: "20px",
  },
  backButton: {
    marginBottom: "16px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
  },
  assetBanner: {
    marginBottom: "24px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "16px",
    borderRadius: "8px",
    border: "1px solid var(--border-color)",
  },
  assetHeader: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    marginBottom: "8px",
    minWidth: 0,
  },
  assetIcon: {
    fontSize: "32px",
    color: "var(--accent-hover)",
  },
  assetInfo: {
    flex: 1,
    minWidth: 0,
  },
  assetName: {
    fontSize: "14px",
    fontWeight: "600",
    color: "var(--text-primary)",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    minWidth: 0,
  },
  hospitalityBadge: {
    backgroundColor: "#0f6cbd",
    color: "#ffffff",
    fontSize: "10px",
    marginTop: "6px",
    width: "fit-content",
  },
  assetIdentifier: {
    fontSize: "12px",
    color: "var(--text-secondary)",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    minWidth: 0,
  },
  permissions: {
    display: "column",
    gap: "4px",
    flexShrink: 0,
    maxWidth: "45%",
    overflow: "hidden",
  },
  badge: {
    background: "var(--success-bg)",
    color: "var(--success-text)",
    fontSize: "9px",
    lineHeight: 1,
    minHeight: "18px",
    maxWidth: "72px",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  baseFileCard: {
    marginBottom: "24px",
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
    },
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
  },
  cardTitle: {
    fontSize: "15px",
    fontWeight: "600",
    flex: 1,
  },
  cardSubtitle: {
    fontSize: "12px",
    color: "var(--text-secondary)",
    marginTop: "6px",
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
    backgroundColor: "#2b3331",
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
  loadButton: {
    width: "100%",
    background: "var(--accent-hover)",
    color: "var(--text-primary)",
    border: "none",
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
  actionButtons: {
    display: "flex",
    gap: "8px",
    marginTop: "12px",
    justifyContent: "flex-end",
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
  progressCard: {
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "8px 12px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
    marginBottom: "12px",
  },
  progressSpinner: {
    display: "flex",
    justifyContent: "center",
    marginBottom: "4px",
  },
  progressStatus: {
    color: "var(--success-text)",
    fontSize: "10px",
    textAlign: "center",
    marginBottom: "6px",
  },
});

const AssetScenarioDetail = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const styles = useStyles();
  const project = location.state?.project;
  const asset = location.state?.asset;
  const modelLabel = asset?.is_hospitality ? "Hospitality" : "AssetCo";
  const { apiService } = useAuth();

  const [scenarios, setScenarios] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingScenarios, setIsLoadingScenarios] = useState(true);
  const [isCalculating, setIsCalculating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [saveOptionsDialogOpen, setSaveOptionsDialogOpen] = useState(false);
  const [saveAsDialogOpen, setSaveAsDialogOpen] = useState(false);
  const [selectScenarioForOverwriteOpen, setSelectScenarioForOverwriteOpen] = useState(false);
  const [shareDialogOpen, setShareDialogOpen] = useState(false);
  const [scenarioName, setScenarioName] = useState("");

  const [users, setUsers] = useState([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [isSharing, setIsSharing] = useState(false);
  const [isNormalising, setIsNormalising] = useState(false);
  const [calculationStatus, setCalculationStatus] = useState("");
  const [hasTemplateSheets, setHasTemplateSheets] = useState(false);
  const [cachedNamedItems, setCachedNamedItems] = useState(null);

  useEffect(() => {
    const fetchScenarios = async () => {
      if (!project?.id || !asset?.id) return;

      try {
        setIsLoadingScenarios(true);
        const response = await apiService.fetchAssetScenarios(project.id, asset.id);
        setScenarios(response.scenarios || []);
      } catch (error) {
        console.error("Failed to fetch asset scenarios:", error);
        showToast("Failed to load scenarios", "error");
      } finally {
        setIsLoadingScenarios(false);
      }
    };

    fetchScenarios();
  }, [project?.id, asset?.id]);

  const showToast = (message, type = "success") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      removeToast(id);
    }, 5000);
  };
  useEffect(() => {
    const checkTemplateSheets = async () => {
      try {
        await Excel.run(async (context) => {
          const sheets = context.workbook.worksheets;
          sheets.load("items/name");
          await context.sync();

          const sheetNames = sheets.items.map((s) => s.name);
          const requiredTemplates = ["AC - CFS Template", "LC - CFS Template", "DC - CFS Template"];

          // Check if all required templates exist
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
    const loadAllNamedItems = async () => {
      try {
        const refs = await buildNamedItemCache([
          "s.assetco", "a.assetco", "dd.assetco", "o.assetco",
          "o.hospitality", "a.hospitality", "s.hospitality", "dd.hospitality",
        ]);
        setCachedNamedItems(refs);
      } catch (err) {
        console.error("Failed to pre-load named items:", err);
      }
    };
    loadAllNamedItems();
  }, []);

  async function getUserDefinedNamedRanges(preloadedItems = null) {
    return readNamedRangesByPrefixes(
      ["s.assetco", "a.assetco", "dd.assetco", "o.assetco", "o.hospitality", "a.hospitality", "s.hospitality", "dd.hospitality"],
      preloadedItems
    );
  }

  const removeToast = (id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  };

  const isExcelWeb = () => {
    return Office.context.platform === Office.PlatformType.OfficeOnline;
  };

  async function getSheetsInserted() {
    if (!asset?.id || !project?.id) {
      showToast("No base file available for this asset", "error");
      return;
    }

    setIsDownloading(true);
    try {
      if (isExcelWeb()) {
        showToast("Please use Excel Desktop to import template.", "error");
        return;
      }

      const fileResponse = await apiService.downloadAssetBaseFile(project.id, asset.id);

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

        for (let i = worksheets.items.length - 1; i >= 0; i--) {
          const sheet = worksheets.items[i];
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

        await context.sync();
      });

      await Excel.run(async (context) => {
        const sheets = context.workbook.worksheets;
        sheets.load("items/name");
        await context.sync();

        const sheetNames = sheets.items.map((s) => s.name);
        const requiredTemplates = ["AC - CFS Template", "DC - CFS Template", "LC - CFS Template"];

        const allTemplatesExist = requiredTemplates.some((template) =>
          sheetNames.includes(template)
        );

        setHasTemplateSheets(allTemplatesExist);
      });

      showToast("Asset template downloaded successfully!", "success");
    } catch (error) {
      console.error("Failed to download template:", error);
      if (isExcelWeb()) {
        showToast("Failed to import template. Please use Excel Desktop.", "error");
      } else {
        showToast(error.message || "Failed to download template", "error");
      }
    } finally {
      setIsDownloading(false);
    }
  }

  const handleDownloadTemplate = async () => {
    await getSheetsInserted();
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

  const handleScenarioSelect = (event) => {
    const scenarioId = parseInt(event.target.value, 10);
    const scenario = scenarios.find((s) => s.id === scenarioId);
    setSelectedScenario(scenario);
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
  async function pasteDataIntoNamedRanges(context, inputData) {
    if (!Array.isArray(inputData) || inputData.length === 0) return;

    const isFormulaLike = (value) => {
      if (typeof value !== "string") return false;
      const trimmed = value.trim();
      return trimmed.startsWith("=") || trimmed.startsWith("{=");
    };

    const normalizeFormulaForWrite = (value) => {
      if (typeof value !== "string") return value;
      const trimmed = value.trim();
      if (trimmed.startsWith("{=") && trimmed.endsWith("}")) {
        return trimmed.slice(1, -1);
      }
      return trimmed;
    };

    const workbook = context.workbook;
    const pending = inputData.map((item) => {
      const namedItem = workbook.names.getItem(item.name);
      const range = namedItem.getRange();
      range.load("formulas,rowCount,columnCount");
      return { item, range };
    });

    await context.sync();
    context.application.suspendApiCalculationUntilNextSync();
    context.application.suspendScreenUpdatingUntilNextSync();

    const errors = [];
    for (const { item, range } of pending) {
      try {
        console.log(`Pasting data for named range: ${item.name}`);
        const formulasToRestore = item.values.map((row, rowIndex) =>
          row.map((cellValue, colIndex) => {
            const existingFormula = range.formulas?.[rowIndex]?.[colIndex];
            return isFormulaLike(existingFormula)
              ? normalizeFormulaForWrite(existingFormula)
              : cellValue;
          })
        );

        range.values = item.values;
        range.formulas = formulasToRestore;
      } catch (err) {
        console.error(`Failed to paste ${item.name}`, err);
        errors.push(err);
      }
    }

    if (errors.length) {
      throw new Error(errors.map((err) => err.message).join("\n"));
    }
  }

  const handleLoadScenario = async () => {
    if (!selectedScenario) return;

    setIsLoading(true);
    try {
      const scenarioData = await apiService.loadAssetScenario(
        project.id,
        asset.id,
        selectedScenario.id
      );

      const outputData = scenarioData.scenario.output_json;
      const inputData = scenarioData.scenario.input_json;

      await Excel.run(async (context) => {
        await pasteDataIntoNamedRanges(context, inputData);

        if (!outputData) {
          throw new Error("No output data found in scenario");
        }

        context.application.calculationMode = Excel.CalculationMode.manual;
        await context.sync(); // commit manual mode before writes
        context.application.suspendApiCalculationUntilNextSync();
        context.application.suspendScreenUpdatingUntilNextSync();

        try {
          await processASSETCOOutputTemplate(context, outputData);
        } finally {
          context.application.calculationMode = Excel.CalculationMode.automatic;
          await context.sync();
        }
      });

      showToast(`Scenario "${selectedScenario.name}" loaded successfully!`, "success");
    } catch (error) {
      console.error("Failed to load scenario:", error);
      showToast(error.message || "Failed to load scenario", "error");
    } finally {
      setIsLoading(false);
    }
  };

  const handleCalculations = async () => {
    if (!project?.id || !asset?.id) return;

    setIsCalculating(true);
    setCalculationStatus(`Running ${modelLabel} calculations...`);

    try {
      const namedRanges = await getUserDefinedNamedRanges(cachedNamedItems);
      console.log("Collected named ranges for calculations:", namedRanges);
      const response = await apiService.calculateAssetCo(namedRanges, {
        is_hospitality: !!asset?.is_hospitality,
      });

      await Excel.run(async (context) => {
        context.application.calculationMode = Excel.CalculationMode.manual;
        await context.sync(); // commit manual mode before writes

        context.application.suspendApiCalculationUntilNextSync();
        context.application.suspendScreenUpdatingUntilNextSync();

        try {
          await processASSETCOOutputTemplate(context, response);
        } finally {
          context.application.calculationMode = Excel.CalculationMode.automatic;
          await context.sync();
        }
      });

      showToast(`${modelLabel} calculations completed successfully!`, "success");
      setCalculationStatus("Calculations completed!");

      setTimeout(() => {
        setCalculationStatus("");
      }, 3000);
    } catch (error) {
      console.error("Failed to run calculations:", error);
      setCalculationStatus("Calculations failed!");
      showToast(error.message || "Failed to run calculations", "error");
    } finally {
      setIsCalculating(false);
    }
  };

  const handleSaveScenario = async () => {
    if (!project?.permissions?.write_access) {
      showToast("Write access required to save scenarios", "error");
      return;
    }
    // Open dialog to choose between Save and Save As
    setSaveOptionsDialogOpen(true);
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
    if (!scenarioName.trim()) {
      showToast("Please enter a scenario name", "error");
      return;
    }

    setIsSaving(true);
    setSaveAsDialogOpen(false);

    try {
      const namedRanges = await getUserDefinedNamedRanges(cachedNamedItems);

      const response = await apiService.saveIteration({
        project_id: project.id,
        asset_id: asset.id,
        name: scenarioName,
        iteration_type: "assetco",
        input_json: namedRanges,
      });
      if (response?.iteration_id) {
        // apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
        //   console.error("Failed to normalise scenario:", normaliseError);
        //   // showToast(normaliseError.message || "Failed to normalise scenario", "error");
        // });
      }

      showToast(`Scenario "${scenarioName}" saved successfully!`, "success");
      setScenarioName("");

      // Refresh scenarios list
      const response2 = await apiService.fetchAssetScenarios(project.id, asset.id);
      setScenarios(response2.scenarios || []);
    } catch (error) {
      console.error("Failed to save scenario:", error);
      showToast(error.message || "Failed to save scenario", "error");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveAsCancel = () => {
    setSaveAsDialogOpen(false);
    setScenarioName("");
  };

  const handleSaveOptionsCancel = () => {
    setSaveOptionsDialogOpen(false);
  };

  const handleConfirmOverwrite = async (scenario) => {
    setSelectScenarioForOverwriteOpen(false);
    setIsSaving(true);
    try {
      const namedRanges = await getUserDefinedNamedRanges(cachedNamedItems);
      const response = await apiService.saveIteration({
        project_id: project.id,
        asset_id: asset.id,
        iteration_id: scenario.id,
        name: scenario.name,
        iteration_type: "assetco",
        input_json: namedRanges,
      });
      if (response?.iteration_id) {
        // apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
        //   console.error("Failed to normalise scenario:", normaliseError);
        //   // showToast(normaliseError.message || "Failed to normalise scenario", "error");
        // });
      }
      showToast(`Scenario "${scenario.name}" updated successfully!`, "success");
      const response2 = await apiService.fetchAssetScenarios(project.id, asset.id);
      setScenarios(response2.scenarios || []);
    } catch (error) {
      console.error("Failed to overwrite scenario:", error);
      showToast(error.message || "Failed to overwrite scenario", "error");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSelectScenarioCancel = () => setSelectScenarioForOverwriteOpen(false);

  const handleShareScenario = () => {
    if (!selectedScenario) {
      showToast("Please select a scenario to share", "error");
      return;
    }
    fetchUsersList();
    setShareDialogOpen(true);
  };

  const fetchUsersList = async () => {
    setIsLoadingUsers(true);
    try {
      const response = await apiService.fetchUsersDetails();
      let usersList = [];
      if (Array.isArray(response)) {
        usersList = response;
      } else if (response && Array.isArray(response.users)) {
        usersList = response.users;
      } else if (response && response.data && Array.isArray(response.data)) {
        usersList = response.data;
      }

      if (usersList.length > 0) {
        setUsers(usersList);
      } else {
        showToast("No users available to share with", "info");
        setUsers([]);
      }
    } catch (error) {
      console.error("Failed to fetch users:", error);
      showToast("Failed to load users list: " + error.message, "error");
      setUsers([]);
    } finally {
      setIsLoadingUsers(false);
    }
  };

  const handleShareConfirm = async (user) => {
    setIsSharing(true);
    setShareDialogOpen(false);
    try {
      await apiService.shareIteration({
        iteration_id: selectedScenario.id,
        target_user_id: user.username,
      });
      showToast(`Scenario shared successfully with ${user.username}!`, "success");
    } catch (error) {
      console.error("Failed to share scenario:", error);
      showToast(error.message || "Failed to share scenario", "error");
    } finally {
      setIsSharing(false);
    }
  };

  const handleShareCancel = () => {
    setShareDialogOpen(false);
  };

  const handleNormalise = async () => {
    if (!selectedScenario) return;
    setIsNormalising(true);
    try {
      await apiService.normaliseIteration(selectedScenario.id);
      showToast("Scenario normalised successfully!", "success");
    } catch (error) {
      showToast(error.message || "Failed to normalise scenario", "error");
    } finally {
      setIsNormalising(false);
    }
  };

  if (!project || !asset) {
    return (
      <div className={styles.container}>
        <div className={styles.content}>
          <h3>No Asset Selected</h3>
          <Button
            icon={<ArrowLeft24Regular />}
            onClick={() => navigate("/assetco", { state: { project } })}
          >
            Back to Assets
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
        {/* Asset Banner */}
        <div className={styles.assetBanner}>
          <div className={styles.assetHeader}>
            <div className={styles.assetIcon}>
              <Building24Regular />
            </div>
            <div className={styles.assetInfo}>
              <div className={styles.assetName}>
                {asset.asset_name}
                <span className={styles.assetIdentifier}>
                  | {asset.asset_unique_identifier || "No identifier"}
                </span>
              </div>
              {asset.is_hospitality && (
                <Badge
                  className={styles.hospitalityBadge}
                  size="small"
                  style={{ backgroundColor: "#0f6cbd", color: "#ffffff" }}
                >
                  Hospitality
                </Badge>
              )}
            </div>
            <div className={styles.permissions}>
              {project.permissions?.read_access && (
                <Badge className={styles.badge} size="small">
                  Read
                </Badge>
              )}
              {hasWriteAccess && (
                <Badge className={styles.badge} size="small">
                  Write
                </Badge>
              )}
            </div>
          </div>
        </div>

        {/* Download Base File Card */}
        <Card
          className={styles.baseFileCard}
          onClick={hasTemplateSheets || isDownloading ? undefined : handleDownloadTemplate}
          style={{
            opacity: hasTemplateSheets || isDownloading ? 0.5 : 1,
            cursor: hasTemplateSheets || isDownloading ? "not-allowed" : "pointer",
          }}
        >
          <div className={styles.cardHeader}>
            <ArrowDownload24Regular style={{ fontSize: "24px" }} />
            <div style={{ flex: 1 }}>
              <div className={styles.cardTitle}>
                {isDownloading
                  ? "Downloading..."
                  : hasTemplateSheets
                    ? "Base File Already Loaded"
                    : "Asset Base File"}
              </div>
              <div className={styles.cardSubtitle}>
                {isDownloading
                  ? "Preparing download..."
                  : hasTemplateSheets
                    ? "All template sheets are already in the workbook"
                    : "Download asset-specific template"}
              </div>
            </div>
          </div>
        </Card>

        {/* Scenarios Dropdown Section */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Load Saved Scenario</div>
          {isLoadingScenarios ? (
            <div style={{ textAlign: "center", padding: "20px", color: "var(--text-secondary)" }}>
              <Spinner size="small" />
              <div style={{ marginTop: "8px" }}>Loading scenarios...</div>
            </div>
          ) : scenarios.length === 0 ? (
            <div style={{ textAlign: "center", padding: "20px", color: "var(--text-secondary)" }}>
              No scenarios available for this asset
            </div>
          ) : (
            <>
              <SearchableDropdown
                options={scenarios.map((s) => ({ value: s.id, label: s.name }))}
                value={selectedScenario ? String(selectedScenario.id) : ""}
                onChange={(val) => {
                  const scenario = scenarios.find((s) => String(s.id) === String(val));
                  setSelectedScenario(scenario || null);
                }}
                placeholder="Choose a scenario to load"
              />
              <div className={styles.actionButtons}>
                <Button
                  appearance="secondary"
                  size="small"
                  onClick={handleLoadScenario}
                  disabled={!selectedScenario || isLoading}
                >
                  {isLoading ? "Loading..." : "Load Scenario"}
                </Button>
                <Button
                  appearance="secondary"
                  size="small"
                  onClick={handleShareScenario}
                  disabled={!selectedScenario || isSharing || !hasWriteAccess}
                >
                  {isSharing ? "Sharing..." : "Share"}
                </Button>
                {/* <Button
                  appearance="secondary"
                  size="small"
                  onClick={handleNormalise}
                  disabled={!selectedScenario || isNormalising}
                >
                  {isNormalising ? "Normalising..." : "Normalise"}
                </Button> */}
              </div>
            </>
          )}
        </div>

        {/* Calculation Progress */}
        {calculationStatus && (
          <Card className={styles.progressCard}>
            {isCalculating && (
              <div className={styles.progressSpinner}>
                <Spinner size="extra-tiny" />
              </div>
            )}
            <div className={styles.progressStatus}>{calculationStatus}</div>
          </Card>
        )}

        {/* Action Cards Grid */}
        <div className={styles.actionsGrid}>
          {/* Calculations Card */}
          <Card
            className={styles.actionCard}
            onClick={isCalculating ? undefined : handleCalculations}
            style={isCalculating ? { opacity: 0.6, cursor: "wait" } : {}}
          >
            <div className={styles.actionIcon}>
              <Calculator24Regular />
            </div>
            <div className={styles.actionTitle}>
              {isCalculating ? "Calculating..." : "Run Calculations"}
            </div>
            <div className={styles.actionDescription}>
              {isCalculating
                ? `Processing ${modelLabel} model...`
                : `Execute ${modelLabel} calculations`}
            </div>
          </Card>

          {/* Save Scenario Card */}
          <Card
            className={hasWriteAccess ? styles.actionCard : styles.actionCardDisabled}
            onClick={hasWriteAccess && !isSaving ? handleSaveScenario : undefined}
            style={isSaving ? { opacity: 0.6, cursor: "wait" } : {}}
          >
            <div className={styles.actionIcon}>
              <Save24Regular />
            </div>
            <div className={styles.actionTitle}>{isSaving ? "Saving..." : "Save Scenario"}</div>
            <div className={styles.actionDescription}>
              {isSaving
                ? "Saving scenario data..."
                : hasWriteAccess
                  ? "Save current scenario"
                  : "Write access required"}
            </div>
          </Card>
        </div>
      </div>

      <SaveOptionsDialog
        open={saveOptionsDialogOpen}
        onClose={handleSaveOptionsCancel}
        onSaveExisting={handleSaveExisting}
        onSaveAsNew={handleSaveAsNew}
      />

      {/* Save As Dialog - Enter new scenario name */}
      <Dialog
        open={saveAsDialogOpen}
        onOpenChange={(event, data) => setSaveAsDialogOpen(data.open)}
      >
        <DialogSurface
          style={{
            background: "var(--bg-secondary)",
            color: "var(--text-primary)",
            border: "1px solid var(--border-color)",
          }}
        >
          <DialogBody>
            <DialogTitle
              style={{ fontSize: "18px", fontWeight: "600", color: "var(--text-primary)" }}
            >
              Save As New Scenario
            </DialogTitle>
            <DialogContent style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <Label
                htmlFor="newScenarioName"
                required
                style={{ fontSize: "14px", fontWeight: "500", color: "var(--text-primary)" }}
              >
                Scenario Name
              </Label>
              <Input
                id="newScenarioName"
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
                placeholder="Enter new scenario name"
                autoFocus
                style={{ backgroundColor: "var(--bg-secondary)", color: "var(--text-primary)" }}
              />
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                onClick={handleSaveAsCancel}
                style={{
                  background: "var(--bg-tertiary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border-color)",
                }}
              >
                Cancel
              </Button>
              <Button
                appearance="primary"
                onClick={handleSaveAsNewConfirm}
                disabled={!scenarioName.trim()}
                style={{
                  background: "var(--accent-hover)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--accent-hover)",
                }}
              >
                Save As New
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* Select Scenario for Overwrite Dialog */}
      <OverwriteDialog
        open={selectScenarioForOverwriteOpen}
        onClose={handleSelectScenarioCancel}
        onConfirm={handleConfirmOverwrite}
        isSaving={isSaving}
        scenarios={scenarios}
      />

      {/* Share Scenario Dialog */}
      <ShareDialog
        open={shareDialogOpen}
        onClose={handleShareCancel}
        onShare={handleShareConfirm}
        isSharing={isSharing}
        title={`Share Scenario: ${selectedScenario?.name}`}
        users={users}
        isLoadingUsers={isLoadingUsers}
      />
    </div>
  );
};

export default AssetScenarioDetail;
