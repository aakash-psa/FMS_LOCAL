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
  Folder24Regular,
  CheckmarkCircle24Regular,
  Edit24Regular,
  Document24Regular,
  DocumentTableArrowRight24Regular,
  Calculator24Regular,
  Save24Regular,
  Open24Regular,
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
  projectBanner: {
    marginBottom: "24px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "12px 16px",
    borderRadius: "8px",
    border: "1px solid var(--border-color)",
    display: "flex",
    alignItems: "center",
    gap: "12px",
  },
  projectInfo: {
    flex: 1,
  },
  projectName: {
    fontSize: "16px",
    fontWeight: "600",
    marginBottom: "4px",
  },
  projectMeta: {
    fontSize: "12px",
    color: "var(--text-secondary)",
  },
  permissions: {
    display: "flex",
    gap: "6px",
  },
  badge: {
    background: "var(--success-bg)",
    color: "var(--success-text)",
    fontSize: "11px",
  },
  scenariosSection: {
    marginTop: "20px",
  },
  scenariosHeader: {
    color: "var(--text-primary)",
    fontSize: "18px",
    fontWeight: "500",
    marginBottom: "16px",
  },
  emptyState: {
    color: "var(--text-secondary)",
    textAlign: "center",
    padding: "40px",
    fontSize: "14px",
    background: "var(--bg-secondary)",
    borderRadius: "8px",
    border: "1px solid var(--border-color)",
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
      boxShadow: "var(--card-shadow)",
    },
  },
  scenarioCard: {
    marginBottom: "12px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "14px 16px",
    borderRadius: "8px",
    border: "1px solid var(--border-color)",
    cursor: "pointer",
    transition: "all 0.2s ease",
    "&:hover": {
      background: "var(--bg-tertiary)",
      transform: "translateX(4px)",
      boxShadow: "var(--card-shadow)",
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
  scenariosList: {
    marginTop: "12px",
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
    "&:focus-within": {
      boxShadow: "0 0 0 2px color-mix(in srgb, var(--accent-hover) 35%, transparent)",
    },
  },
  loadButton: {
    width: "100%",
    background: "var(--accent-hover)",
    color: "var(--text-primary)",
    border: "none",
    "&:hover": {
      background: "var(--bg-tertiary)",
    },
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
      boxShadow: "var(--card-shadow)",
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
  dialogContent: {
    display: "flex",
    flexDirection: "column",
    gap: "16px",
  },
  input: {
    width: "100%",
  },
  progressCard: {
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "8px 12px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
    marginBottom: "12px",
  },
  progressTitle: {
    color: "var(--text-primary)",
    fontSize: "11px",
    fontWeight: "600",
    marginBottom: "6px",
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
  dropdownOption: {
    backgroundColor: "var(--bg-secondary)",
    color: "var(--text-primary)",
    "&:hover": {
      backgroundColor: "var(--bg-tertiary)",
    },
  },
  dialogSurface: {
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
  },
  dialogTitle: {
    fontSize: "18px",
    fontWeight: "600",
    color: "var(--text-primary)",
  },
  dialogLabel: {
    fontSize: "14px",
    fontWeight: "500",
    color: "var(--text-primary)",
  },
  dialogInput: {
    backgroundColor: "var(--bg-secondary)",
    color: "var(--text-primary)",
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
});

const Scenarios = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const styles = useStyles();
  const project = location.state?.project;
  const { apiService, downloadTemplate } = useAuth();

  const [scenarios, setScenarios] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingScenarios, setIsLoadingScenarios] = useState(true);
  const [isCalculating, setIsCalculating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [calculationError, setCalculationError] = useState(null);
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
  const [isOverwriting, setIsOverwriting] = useState(false);
  const [calculationStatus, setCalculationStatus] = useState("");
  const [modelStatuses, setModelStatuses] = useState({});
  const [hasTemplateSheets, setHasTemplateSheets] = useState(false);

  const [scenarioSearch, setScenarioSearch] = useState("");
  const [scenarioDropdownOpen, setScenarioDropdownOpen] = useState(false);

  // Cached workbook + worksheet named items, loaded once on mount
  const [cachedNamedItems, setCachedNamedItems] = useState(null);

  // Fetch scenarios on component mount using unified POST API
  useEffect(() => {
    const fetchScenarios = async () => {
      if (!project?.id) return;

      try {
        setIsLoadingScenarios(true);
        const data = await apiService.fetchProjectScenarios(project.id);
        setScenarios(data.scenarios || []);
      } catch (error) {
        console.error("Failed to fetch scenarios:", error);
        showToast("Failed to load scenarios", "error");
      } finally {
        setIsLoadingScenarios(false);
      }
    };

    fetchScenarios();
  }, [project?.id, apiService]);

  // Pre-load all workbook + worksheet named items once so individual
  // calculation helpers can skip the expensive load/sync on each call.

  
  useEffect(() => {
    const loadAllNamedItems = async () => {
      try {
        const namedRefs = await buildNamedItemCache(["s.devco", "a.devco", "s.landco", "a.landco"]);
        setCachedNamedItems(namedRefs);
      } catch (err) {
        console.error("Failed to pre-load named items:", err);
      }
    };

    loadAllNamedItems();
  }, []);

  // Check for template sheets on component mount
  useEffect(() => {
    const checkTemplateSheets = async () => {
      try {
        await Excel.run(async (context) => {
          const sheets = context.workbook.worksheets;
          sheets.load("items/name");
          await context.sync();

          const sheetNames = sheets.items.map((s) => s.name);
          const requiredTemplates = ["DC - CFS Template", "LC - CFS Template", "AC - CFS Template"];

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

  const showToast = (message, type = "success") => {
    const id = Date.now() + Math.random(); // Ensure unique ID to prevent duplicates
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      removeToast(id);
    }, 5000);
  };

  const removeToast = (id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  };

  // Add utility function to check if running in Excel Web
  const isExcelWeb = () => {
    return Office.context.platform === Office.PlatformType.OfficeOnline;
  };

  async function getSheetsInserted() {
    if (!project?.id) return;

    setIsDownloading(true);
    try {
      if (isExcelWeb()) {
        showToast(`Please use Excel Desktop to import template.`, "error");
        setIsDownloading(false);
        return;
      }
      const fileResponse = await downloadTemplate(project.id);
      if (!fileResponse || !fileResponse.file_base64) {
        showToast("No file data received from server", "error");
        setIsDownloading(false);
        return;
      }
      // Check if running in Excel Web and file size exceeds 5MB

      await Excel.run(async (context) => {
        const workbook = context.workbook;
        const worksheets = workbook.worksheets;

        worksheets.load("items/name");
        await context.sync();

        console.log(
          "Worksheets before deletion:",
          worksheets.items.map((s) => s.name)
        );

        // Add a temporary blank sheet first
        const tempSheet = worksheets.add("Temp");
        await context.sync();

        // Delete all original sheets
        for (let i = worksheets.items.length - 1; i >= 0; i--) {
          const sheet = worksheets.items[i];
          if (sheet.name !== "Temp") {
            console.log(`Deleting sheet: ${sheet.name}`);
            sheet.delete();
          }
        }

        await context.sync();

        // Rename the temp sheet to something meaningful
        tempSheet.name = "Sheet1";
        await context.sync();

        const base64 = fileResponse.file_base64;

        workbook.insertWorksheetsFromBase64(base64, {
          sheetNamesToInsert: null,
          positionType: Excel.WorksheetPositionType.end,
        });

        console.log("All sheets deleted and replaced with a blank sheet");
      });

      showToast("Template imported successfully!", "success");

      // Re-check template sheets after import to disable button
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
    } catch (err) {
      console.error("Failed to import template:", err);

      // Show specific error message for Excel Web users
      if (isExcelWeb()) {
        showToast(
          "Failed to import template. Excel Web does not support templates with PivotTables, Charts, Comments, or Slicers. Please use Excel Desktop.",
          "error"
        );
      } else {
        showToast("Failed to import template", "error");
      }

      throw err;
    } finally {
      setIsDownloading(false);
    }
  }

  const pasteDataIntoNamedRanges = async (context, inputData) => {
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
      range.load("formulas");
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
  };

  const handleLoadScenario = async () => {
    if (!selectedScenario) return;

    setIsLoading(true);
    try {
      const scenarioData = await apiService.loadScenario(project.id, selectedScenario.id);
      const outputData = scenarioData.scenario.output_json;
      const inputData = scenarioData.scenario.input_json;

      await Excel.run(async (context) => {
        context.application.calculationMode = Excel.CalculationMode.manual;
        await context.sync(); // commit manual mode before writes
        context.application.suspendApiCalculationUntilNextSync();
        context.application.suspendScreenUpdatingUntilNextSync();

        try {
          await pasteDataIntoNamedRanges(context, inputData);

          if (!outputData) {
            throw new Error("No output data found in scenario");
          }

          const processorMap = {
            landco: processOutputTemplate,
            devco: processDEVCOOutputTemplate,
          };

          // Collect errors from each processor so all processors always run.
          // This prevents an early finally/sync from restoring automatic calc
          // mode before the second processor has queued its writes.
          const processorErrors = [];
          for (const [type, processor] of Object.entries(processorMap)) {
            if (outputData[type]) {
              try {
                await processor(context, outputData[type], { preserveExistingFormulas: true });
              } catch (err) {
                processorErrors.push(`${type}: ${err.message}`);
              }
            }
          }

          if (processorErrors.length > 0) {
            throw new Error(processorErrors.join("\n"));
          }
        } finally {
          // Runs once after ALL processors complete — flushes all queued writes
          // and restores calculation mode.
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


  /* global Excel */

  const pasteDataframesToNamedRanges = async (context, sheetName, jobs, options = {}) => {
    if (!Array.isArray(jobs) || jobs.length === 0) return;

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

    const { preserveExistingFormulas = false } = options;

    const overallStart = performance.now();
    console.log(`pasteDataframesToNamedRanges:${sheetName} starting with ${jobs.length} jobs`);

    const workbook = context.workbook;
    const sheet = workbook.worksheets.getItem(sheetName);

    const pending = jobs.map(({ namedRange, dataframeData }) => {
      let range = null;
      let error = null;
      try {
        const namedItem = sheet.names.getItem(namedRange);
        range = namedItem.getRange();
      } catch (sheetError) {
        try {
          const workbookNamedItem = workbook.names.getItem(namedRange);
          range = workbookNamedItem.getRange();
        } catch (wbError) {
          error = new Error(
            `Named range '${namedRange}' not found in sheet '${sheetName}' or workbook. Sheet error: ${sheetError?.message || sheetError}. Workbook error: ${wbError?.message || wbError}`
          );
        }
      }

      return { namedRange, dataframeData, range, error };
    });

    const totalCells = pending.reduce((sum, item) => {
      const data = item.dataframeData;
      if (!Array.isArray(data) || data.length === 0) return sum;
      const rows = data.length;
      const cols = Array.isArray(data[0]) ? data[0].length : 0;
      return sum + rows * cols;
    }, 0);
    console.log(`pasteDataframesToNamedRanges:${sheetName} queued ${totalCells} cells for write`);

    const errors = [];

    if (preserveExistingFormulas) {
      for (const item of pending) {
        if (!item.error) {
          item.range.load("formulas");
        }
      }
      await context.sync();
      context.application.suspendApiCalculationUntilNextSync();
      context.application.suspendScreenUpdatingUntilNextSync();
    }

    for (const item of pending) {
      if (item.error) {
        errors.push(item.error);
        continue;
      }

      const { range, dataframeData } = item;
      range.values = dataframeData;

      if (preserveExistingFormulas) {
        const formulasToRestore = dataframeData.map((row, rowIndex) =>
          row.map((cellValue, colIndex) => {
            const existingFormula = range.formulas?.[rowIndex]?.[colIndex];
            return isFormulaLike(existingFormula)
              ? normalizeFormulaForWrite(existingFormula)
              : cellValue;
          })
        );

        range.formulas = formulasToRestore;
      }
    }

    if (errors.length) {
      throw new Error(errors.map((err) => err.message).join("\n"));
    }
  };


  const processOutputTemplate = async (context, outputs, options = {}) => {
    const templateSheetName = "LC - CFS Template";
    const targetSheetName = "LC - CFS";
    const jobs = [];

    await ensureTemplateSheetPresent(context, templateSheetName, targetSheetName);

    if (outputs.monthly_dfs) {
      for (const [dfName, dfArr] of Object.entries(outputs.monthly_dfs)) {
        if (dfArr[0] != "o.landco.cff.me" || true) {
          jobs.push({ namedRange: dfArr[0], dataframeData: dfArr[1].data });
        }
      }
    }

    if (outputs.annual_dfs) {
      for (const [dfName, dfArr] of Object.entries(outputs.annual_dfs)) {
        jobs.push({ namedRange: dfArr[0], dataframeData: dfArr[1].data });
      }
    }

    if (jobs.length > 0) {
      console.log(`processOutputTemplate: ${jobs.length} paste jobs for ${targetSheetName}`);
      await pasteDataframesToNamedRanges(context, targetSheetName, jobs, options);
    }

    console.log("processOutputTemplate: Cashflow Statement sheet updated");
  };

  const processDEVCOOutputTemplate = async (context, outputs, options = {}) => {
    const templateSheetName = "DC - CFS Template";
    const targetSheetName = "DC - CFS";
    const jobs = [];

    await ensureTemplateSheetPresent(context, templateSheetName, targetSheetName);

    if (outputs.monthly_dfs) {
      console.log("DEVCO OUTPUT MONTHLY DFS:", outputs.monthly_dfs);
      for (const [dfName, dfArr] of Object.entries(outputs.monthly_dfs)) {
        console.log("Processing DEVCO monthly df:", dfName, dfArr[0]);
        jobs.push({ namedRange: dfArr[0], dataframeData: dfArr[1].data });
      }
    }

    if (outputs.annual_dfs) {
      for (const [dfName, dfArr] of Object.entries(outputs.annual_dfs)) {
        jobs.push({ namedRange: dfArr[0], dataframeData: dfArr[1].data });
      }
    }

    if (jobs.length > 0) {
      console.log(`processDEVCOOutputTemplate: ${jobs.length} paste jobs for ${targetSheetName}`);
      await pasteDataframesToNamedRanges(context, targetSheetName, jobs, options);
    }

    console.log("processDEVCOOutputTemplate: Cashflow Statement sheet updated");
  };

  const handleCalculations = async (context, namedRanges) => {
    if (!project?.id) return;

    setIsCalculating(true);
    setCalculationError(null);
    setCalculationStatus("Running LANDCO calculations...");
    setModelStatuses((prev) => ({ ...prev, LANDCO: "running" }));

    try {
      const start = performance.now();
      const response = await apiService.calculateLandCo(namedRanges);
      console.log("LANDCO Calculation Response:", response);
      await processOutputTemplate(context, response.exceloutput);
      const duration = performance.now() - start;
      console.log(`LANDCO total time: ${duration.toFixed(1)} ms`);
      showToast("LANDCO calculations completed successfully!", "success");
      setCalculationStatus("LANDCO calculations completed!");
      setModelStatuses((prev) => ({ ...prev, LANDCO: "success" }));

      // Log errors if any
      if (response.errors && response.errors.length > 0) {
        const errorMessages = response.errors
          .map((err) => `${err.range || "Unknown"}: ${err.message || err.error || "Error"}`)
          .join("\n");
        setCalculationError(`LANDCO Warnings:\n${errorMessages}`);
      }

      return { success: true, model: "LANDCO", landco: response.exceloutput };
    } catch (error) {
      console.error("Failed to run LANDCO calculations:", error);
      const errorMsg = `LANDCO: ${error.message || "Failed to run calculations"}`;
      setCalculationError((prev) => `${prev ? prev + "\n\n" : ""}${errorMsg}`);
      setCalculationStatus("LANDCO calculations failed!");
      setModelStatuses((prev) => ({ ...prev, LANDCO: "error" }));
      showToast(`LANDCO calculations failed: ${error.message || "Unknown error"}`, "error");
      return { success: false, model: "LANDCO", error: error.message };
    } finally {
      setIsCalculating(false);
    }
  };

  const handleDEVCalculations = async (context, namedRanges) => {
    if (!project?.id) return;

    setIsCalculating(true);
    setCalculationStatus("Running DEVCO calculations...");
    setModelStatuses((prev) => ({ ...prev, DEVCO: "running" }));

    try {
      const start = performance.now();
      const response = await apiService.calculateDevCo(namedRanges);
      console.log("DEVCO Calculation Response:", response);
      await processDEVCOOutputTemplate(context, response.exceloutput);
      const duration = performance.now() - start;
      console.log(`DEVCO total time: ${duration.toFixed(1)} ms`);
      showToast("DEVCO calculations completed successfully!", "success");
      setCalculationStatus("DEVCO calculations completed!");
      setModelStatuses((prev) => ({ ...prev, DEVCO: "success" }));

      // Log errors if any
      if (response.errors && response.errors.length > 0) {
        const errorMessages = response.errors
          .map((err) => `${err.range || "Unknown"}: ${err.message || err.error || "Error"}`)
          .join("\n");
        setCalculationError(
          (prev) => `${prev ? prev + "\n\n" : ""}DEVCO Warnings:\n${errorMessages}`
        );
      }

      return { success: true, model: "DEVCO", devco: response.exceloutput };
    } catch (error) {
      console.error("Failed to run DEVCO calculations:", error);
      const errorMsg = `DEVCO: ${error.message || "Failed to run calculations"}`;
      setCalculationError((prev) => `${prev ? prev + "\n\n" : ""}${errorMsg}`);
      setCalculationStatus("DEVCO calculations failed!");
      setModelStatuses((prev) => ({ ...prev, DEVCO: "error" }));
      showToast(`DEVCO calculations failed: ${error.message || "Unknown error"}`, "error");
      return { success: false, model: "DEVCO", error: error.message };
    } finally {
      setIsCalculating(false);
    }
  };

 

 async function getUserDefinedNamedRanges(preloadedItems = null) {
    return readNamedRangesByPrefixes(["s.devco", "a.devco", "s.landco", "a.landco"], preloadedItems);
  }

  const handleAllCalculations = async () => {
    if (!project?.id) return;
    await Excel.run(async (context) => {
      const allStart = performance.now();
      try {
        context.application.calculationMode = Excel.CalculationMode.manual;
        await context.sync(); // commit manual mode before writes
        context.application.suspendApiCalculationUntilNextSync();
        context.application.suspendScreenUpdatingUntilNextSync();
        setModelStatuses({ LANDCO: "pending", DEVCO: "pending" });

        // Load named ranges for both models before running calculations
        const [landcoNamedRanges, devcoNamedRanges] = await Promise.all([
          getUserDefinedNamedRanges_landco(cachedNamedItems),
          getUserDefinedNamedRanges_devco(cachedNamedItems),
        ]);

        // Run calculations in parallel
        const [landcoResult, devcoResult] = await Promise.all([
          handleCalculations(context, landcoNamedRanges), // LANDCO
          handleDEVCalculations(context, devcoNamedRanges), // DEVCO
        ]);

        // Build payload from results
        const payload = {
          landco: landcoResult.success ? landcoResult.landco : {},
          devco: devcoResult.success ? devcoResult.devco : {},
        };

        // Run consolidated calculations ONLY after all three complete

        setCalculationStatus("LANDCO and DEVCO calculations completed!");
        showToast("LANDCO and DEVCO calculations completed!", "success");

        // Clear status after 3 seconds
        setTimeout(() => {
          setCalculationStatus("");
          setModelStatuses({});
        }, 3000);
      } catch (error) {
        console.error("Calculation pipeline error:", error);
        setCalculationStatus("Calculations encountered errors");
        showToast("Calculations encountered errors", "error");
      } finally {
        const allDuration = performance.now() - allStart;
        console.log(`handleAllCalculations total time: ${allDuration.toFixed(1)} ms`);
        context.application.calculationMode = Excel.CalculationMode.automatic;
        await context.sync();
      }
    });
  };

  const handleSaveScenario = async () => {
    if (!project?.id || !project.permissions?.write_access) return;

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
        name: scenarioName,
        iteration_type: "landco_devco",
        input_json: namedRanges,
      });
      // if (response?.iteration_id) {
      //       apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
      //         console.error("Failed to normalise scenario:", normaliseError);
      //         // showToast(normaliseError.message || "Failed to normalise scenario", "error");
      //       });
      //     }
      if (response?.iteration_id) {
        showToast(`Scenario "${scenarioName}" saved successfully!`, "success");
      } else {
        showToast(`Scenario "${scenarioName}" failed to save`, "warning");
      }

      // Refresh scenarios list
      const data = await apiService.fetchProjectScenarios(project.id);
      setScenarios(data.scenarios || []);

      // Clear the input
      setScenarioName("");
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
        iteration_id: scenario.id,
        name: scenario.name,
        iteration_type: "landco_devco",
        input_json: namedRanges,
      });
      //   if (response?.iteration_id) {
      //   apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
      //     console.error("Failed to normalise scenario:", normaliseError);
      //     // showToast(normaliseError.message || "Failed to normalise scenario", "error");
      //   });
      // }
      if (response?.iteration_id) {
        showToast(`Scenario "${scenario.name}" updated successfully!`, "success");
      } else {
        showToast(`Scenario "${scenario.name}" failed to update`, "warning");
      }

      const data = await apiService.fetchProjectScenarios(project.id);
      setScenarios(data.scenarios || []);
    } catch (error) {
      console.error("Failed to overwrite scenario:", error);
      showToast(error.message || "Failed to overwrite scenario", "error");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSelectScenarioCancel = () => setSelectScenarioForOverwriteOpen(false);

  const handleShareScenario = async () => {
    if (!selectedScenario) {
      showToast("Please select a scenario to share", "error");
      return;
    }

    // Fetch users list when opening share dialog
    await fetchUsersList();
    setShareDialogOpen(true);
  };

  const fetchUsersList = async () => {
    setIsLoadingUsers(true);
    try {
      // Fetch users from the admin/users-details API endpoint
      // https://localhost:8000/api/admin/users-details
      const response = await apiService.fetchUsersDetails();

      // Handle response - could be direct array or wrapped in object
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

  async function getUserDefinedNamedRanges_devco(preloadedItems = null) {
    return readNamedRangesByPrefixes(["s.devco", "a.devco", "s.landco", "a.landco"], preloadedItems);
  }

  async function getUserDefinedNamedRanges_landco(preloadedItems = null) {
    return readNamedRangesByPrefixes(["s.landco", "a.landco"], preloadedItems);
  }

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

      <div className={styles.projectBanner}>
        <Folder24Regular />
        <div className={styles.projectInfo}>
          <div className={styles.projectName}>{project.name}</div>
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

      <div className={styles.content}>
        {/* Base File Card - Disabled if templates exist */}
        <Card
          className={styles.baseFileCard}
          onClick={hasTemplateSheets || isDownloading ? undefined : getSheetsInserted}
          style={{
            opacity: hasTemplateSheets || isDownloading ? 0.5 : 1,
            cursor: hasTemplateSheets || isDownloading ? "not-allowed" : "pointer",
          }}
        >
          <div className={styles.cardHeader}>
            <Document24Regular />
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
            <DocumentTableArrowRight24Regular style={{ color: "var(--text-secondary)" }} />
          </div>
        </Card>{" "}
        {/* Scenarios Dropdown Section */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Load Saved Scenario</div>
          {isLoadingScenarios ? (
            <div style={{ textAlign: "center", padding: "20px", color: "var(--text-secondary)" }}>
              Loading scenarios...
            </div>
          ) : scenarios.length === 0 ? (
            <div style={{ textAlign: "center", padding: "20px", color: "var(--text-secondary)" }}>
              No scenarios available
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
                  disabled={!selectedScenario || isSharing}
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
        {/* Calculation Progress Card - Ultra compact version - Only show during calculations */}
        {Object.keys(modelStatuses).length > 0 && (
          <Card className={styles.progressCard}>
            {isCalculating && (
              <div className={styles.progressSpinner}>
                <Spinner size="extra-tiny" />
              </div>
            )}

            <div className={styles.progressStatus}>{calculationStatus}</div>

            {/* Model Status List - Ultra compact */}
            <div>
              {Object.entries(modelStatuses).map(([model, status]) => (
                <div
                  key={model}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "4px 8px",
                    marginBottom: "4px",
                    background: "var(--bg-primary)",
                    borderRadius: "3px",
                    border: `1px solid ${
                      status === "success"
                        ? "var(--success-bg)"
                        : status === "error"
                          ? "var(--error-bg)"
                          : status === "running"
                            ? "var(--info-bg)"
                            : "var(--border-color)"
                    }`,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    {status === "running" && <Spinner size="extra-tiny" />}
                    <span
                      style={{
                        color: "var(--text-primary)",
                        fontSize: "11px",
                        fontWeight: "500",
                      }}
                    >
                      {model}
                    </span>
                  </div>
                  <span
                    style={{
                      color:
                        status === "success"
                          ? "var(--success-text)"
                          : status === "error"
                            ? "var(--error-text)"
                            : status === "running"
                              ? "var(--info-text)"
                              : "var(--text-secondary)",
                      fontSize: "10px",
                    }}
                  >
                    {status === "success"
                      ? "✓"
                      : status === "error"
                        ? "✗"
                        : status === "running"
                          ? "⏳"
                          : "⏸"}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}
        {/* Action Cards Grid */}
        <div className={styles.actionsGrid}>
          {/* Calculations Card */}
          <Card
            className={styles.actionCard}
            onClick={isCalculating ? undefined : handleAllCalculations}
            style={isCalculating ? { opacity: 0.6, cursor: "wait" } : {}}
          >
            <div className={styles.actionIcon}>
              <Calculator24Regular />
            </div>
            <div className={styles.actionTitle}>
              {isCalculating ? "Calculating..." : "Run Calculations"}
            </div>
            <div className={styles.actionDescription}>
              {isCalculating ? "Processing models..." : "Execute Model calculations"}
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
        <DialogSurface className={styles.dialogSurface}>
          <DialogBody>
            <DialogTitle className={styles.dialogTitle}>Save As New Scenario</DialogTitle>
            <DialogContent className={styles.dialogContent}>
              <Label htmlFor="newScenarioName" required className={styles.dialogLabel}>
                Scenario Name
              </Label>
              <Input
                id="newScenarioName"
                className={styles.dialogInput}
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
                placeholder="Enter new scenario name"
                autoFocus
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

export default Scenarios;
