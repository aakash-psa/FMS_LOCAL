import React, { useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Badge,
  makeStyles,
  Button,
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
  Save24Regular,
  Folder24Regular,
  DocumentTableArrowRight20Regular,
  DocumentTableArrowRight24Regular,
  Share24Regular,
} from "@fluentui/react-icons";
import { readNamedRangesByPrefixes, buildNamedItemCache, ensureTemplateSheetPresent } from "../utils/excelNamedRanges";

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
    marginBottom: "12px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    padding: "8px 10px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    width: "100%",
    boxSizing: "border-box",
    flexWrap: "wrap",
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
    flexWrap: "wrap",
  },
  badge: {
    background: "var(--success-bg)",
    color: "var(--success-text)",
    fontSize: "9px",
  },
  section: {
    marginTop: "16px",
    marginBottom: "16px",
    background: "var(--bg-secondary)",
    padding: "12px",
    borderRadius: "6px",
    border: "1px solid var(--border-color)",
    width: "100%",
    maxWidth: "100%",
    boxSizing: "border-box",
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
    flexWrap: "wrap",
  },
  dropdownField: {
    width: "100%",
    minWidth: 0,
    maxWidth: "100%",
    boxSizing: "border-box",
    fontSize: "12px",
    background: "var(--bg-tertiary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
    borderRadius: "6px",
    padding: "4px 36px 4px 12px",
    height: "30px",
    lineHeight: "20px",
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
  dropdownGroup: {
    minWidth: 0,
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

const JVConsolidation = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const styles = useStyles();
  const project = location.state?.project;
  const { apiService } = useAuth();

  const [scenarios, setScenarios] = useState([]);
  const [landcoOptions, setLandcoOptions] = useState([]);
  const [assetcoOptions, setAssetcoOptions] = useState([]);
  const [isLoadingScenarios, setIsLoadingScenarios] = useState(true);
  const [selectedLandcoScenarioId, setSelectedLandcoScenarioId] = useState(null);
  const [selectedAssetcoScenarioId, setSelectedAssetcoScenarioId] = useState(null);
  const [isCalculating, setIsCalculating] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [hasTemplateSheets, setHasTemplateSheets] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [saveOptionsDialogOpen, setSaveOptionsDialogOpen] = useState(false);
  const [saveAsDialogOpen, setSaveAsDialogOpen] = useState(false);
  const [selectScenarioForOverwriteOpen, setSelectScenarioForOverwriteOpen] = useState(false);
  const [savedScenarios, setSavedScenarios] = useState([]);
  const [selectedLoadScenarioId, setSelectedLoadScenarioId] = useState("");
  const [scenarioName, setScenarioName] = useState("");
  const [validationErrors, setValidationErrors] = useState([]);

  const [shareDialogOpen, setShareDialogOpen] = useState(false);

  const [users, setUsers] = useState([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [isSharing, setIsSharing] = useState(false);
  const [isNormalising, setIsNormalising] = useState(false);
  const [selectedScenarioForShare, setSelectedScenarioForShare] = useState(null);
  const [cachedNamedItems, setCachedNamedItems] = useState(null);

  useEffect(() => {
    const checkTemplateSheets = async () => {
      try {
        await Excel.run(async (context) => {
          const sheets = context.workbook.worksheets;
          sheets.load("items/name");
          await context.sync();

          const sheetNames = sheets.items.map((sheet) => sheet.name);
          const requiredTemplates = ["AC - CFS Template", "DC - CFS Template", "LC - CFS Template", "JV - Conso Template"];
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
    const fetchScenarios = async () => {
      if (!project?.id) return;

      try {
        setIsLoadingScenarios(true);
        const response = await apiService.fetchJvScenarios(project.id);
        const landco = response.landco_devco || [];
        const assetco_consolidation = response.assetco || response.assetco_consolidation || [];
        setLandcoOptions(landco);
        setAssetcoOptions(assetco_consolidation);
        setScenarios([...landco, ...assetco_consolidation]);
      } catch (error) {
        console.error("Failed to fetch scenarios:", error);
        showToast("Failed to load project scenarios", "error");
      } finally {
        setIsLoadingScenarios(false);
      }
    };

    fetchScenarios();
  }, [project?.id]);

  useEffect(() => {
    const fetchSavedScenarios = async () => {
      if (!project?.id) return;

      try {
        const response = await apiService.fetchProjectScenarios(project.id, {
          iteration_type: "jv_consolidation",
        });
        setSavedScenarios(response.scenarios || []);
      } catch (error) {
        console.error("Failed to fetch JV consolidation scenarios:", error);
      }
    };

    fetchSavedScenarios();
  }, [project?.id]);

  useEffect(() => {
    const loadAllNamedItems = async () => {
      try {
        const refs = await buildNamedItemCache(["m.jv", "o.jv", "m.mastersheet", "j.jv"]);
        setCachedNamedItems(refs);
      } catch (err) {
        console.error("Failed to pre-load named items:", err);
      }
    };
    loadAllNamedItems();
  }, []);

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

  const handleLandcoSelect = (event) => {
    setSelectedLandcoScenarioId(event.target.value ? parseInt(event.target.value, 10) : null);
  };

  const handleAssetcoSelect = (event) => {
    setSelectedAssetcoScenarioId(event.target.value ? parseInt(event.target.value, 10) : null);
  };

  const validateSelection = () => {
    const errors = [];

    if (!selectedLandcoScenarioId) errors.push("Please select one LandCo/DevCo scenario");
    if (!selectedAssetcoScenarioId) errors.push("Please select one AssetCo scenario");

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

  const handleSaveOptionsCancel = () => setSaveOptionsDialogOpen(false);
  const handleSaveAsCancel = () => {
    setSaveAsDialogOpen(false);
    setScenarioName("");
  };
  const handleSelectScenarioCancel = () => {
    setSelectScenarioForOverwriteOpen(false);
  };

  const handleShareScenario = async () => {
    if (savedScenarios.length === 0) {
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
      showToast("Failed to load users: " + error.message, "error");
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
      await apiService.shareIteration({ iteration_id: scenario.id, target_user_id: user.username });
      showToast(`Scenario shared with ${user.username}!`, "success");
    } catch (error) {
      showToast(error.message || "Failed to share", "error");
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
    if (!selectedLoadScenarioId) return;
    const scenario = savedScenarios.find((s) => String(s.id) === String(selectedLoadScenarioId));
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
    if (!selectedLoadScenarioId) return;
    setIsNormalising(true);
    try {
      await apiService.normaliseIteration(parseInt(selectedLoadScenarioId, 10));
      showToast("Scenario normalised successfully!", "success");
    } catch (error) {
      showToast(error.message || "Failed to normalise scenario", "error");
    } finally {
      setIsNormalising(false);
    }
  };

  const handleConfirmOverwrite = async (scenario) => {
    setSelectScenarioForOverwriteOpen(false);
    setIsSaving(true);
    try {
      const selectedLandco = landcoOptions.find(
        (item) => item.jv_iteration_id === selectedLandcoScenarioId
      );
      const selectedAssetco = assetcoOptions.find(
        (item) => item.jv_iteration_id === selectedAssetcoScenarioId
      );
      const namedranges = await getUserDefinedNamedRanges(cachedNamedItems);
      const payload = {
        namedranges,
        selected_scenarios: [
          {
            source_type: "landco_devco",
            jv_iteration_id: selectedLandco?.jv_iteration_id,
            iteration_id: selectedLandco?.iteration_id,
            scenario_name: selectedLandco?.name,
          },
          {
            source_type: "assetco_consolidation",
            jv_iteration_id: selectedAssetco?.jv_iteration_id,
            iteration_id: selectedAssetco?.iteration_id,
            scenario_name: selectedAssetco?.name,
          },
        ],
      };
      const response = await apiService.saveIteration({
        project_id: project.id,
        iteration_id: scenario.id,
        name: scenario.name,
        iteration_type: "jv_consolidation",
        input_json: payload,
        output_json: payload,
      });
      if (response?.iteration_id) {
        // apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
        //   console.error("Failed to normalise scenario:", normaliseError);
        //   // showToast(normaliseError.message || "Failed to normalise scenario", "error");
        // });
      }
      showToast(`Scenario "${scenario.name}" updated successfully!`, "success");
      const res = await apiService.fetchProjectScenarios(project.id, {
        iteration_type: "jv_consolidation",
      });
      setSavedScenarios(res.scenarios || []);
    } catch (error) {
      showToast(error.message || "Failed to overwrite scenario", "error");
    } finally {
      setIsSaving(false);
    }
  };

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
    if (!selectedLoadScenarioId) {
      showToast("Please select a scenario to load", "error");
      return;
    }

    try {
      const response = await apiService.loadScenario(project.id, selectedLoadScenarioId);
      const scenario = response?.scenario || response;
      const selected = scenario?.input_json?.selected_scenarios || [];
      const inputData = scenario?.input_json?.namedRanges;
      const outputData = scenario?.output_json;

      const landco = selected.find((item) => item.source_type === "landco_devco");
      const assetco_consolidation =
        selected.find((item) => item.source_type === "assetco_consolidation") ||
        selected.find((item) => item.source_type === "assetco");

      setSelectedLandcoScenarioId(landco?.jv_iteration_id || null);
      setSelectedAssetcoScenarioId(assetco_consolidation?.jv_iteration_id || null);
      setValidationErrors([]);

      await Excel.run(async (context) => {
        context.application.calculationMode = Excel.CalculationMode.manual;
        await context.sync();

        context.application.suspendApiCalculationUntilNextSync();
        context.application.suspendScreenUpdatingUntilNextSync();

        try {
          await pasteDataIntoNamedRanges(context, inputData);

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
      console.error("Failed to load JV consolidation scenario:", error);
      showToast(error.message || "Failed to load JV consolidation scenario", "error");
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
    const templateSheetName = "JV - Conso Template";
    const cashflowSheetName = "JV - Output";

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
  async function getUserDefinedNamedRanges(preloadedItems = null) {
    return readNamedRangesByPrefixes(["m.jv", "o.jv", "m.mastersheet", "j.jv"], preloadedItems);
  }
  const handleCalculations = async () => {
    const errors = validateSelection();
    if (errors.length > 0) {
      setValidationErrors(errors);
      showToast("Please complete scenario selection before calculation", "error");
      return;
    }

    setIsCalculating(true);
    try {
      const selectedLandco = landcoOptions.find(
        (item) => item.jv_iteration_id === selectedLandcoScenarioId
      );
      const selectedAssetco = assetcoOptions.find(
        (item) => item.jv_iteration_id === selectedAssetcoScenarioId
      );
      const namedranges = await getUserDefinedNamedRanges(cachedNamedItems);
      const payload = {
        calculation_module: "jv_consolidation",
        project_id: project.id,
        input_json: {
          namedranges,
          selected_scenarios: [
            {
              source_type: "landco_devco",
              jv_iteration_id: selectedLandco?.jv_iteration_id,
              iteration_id: selectedLandco?.iteration_id,
              scenario_name: selectedLandco?.name,
            },
            {
              source_type: "assetco_consolidation",
              jv_iteration_id: selectedAssetco?.jv_iteration_id,
              iteration_id: selectedAssetco?.iteration_id,
              scenario_name: selectedAssetco?.name,
            },
          ],
        },
      };

      const response = await apiService.calculateConsolidated(payload);
      await Excel.run(async (context) => {
        context.application.calculationMode = Excel.CalculationMode.manual;
        await context.sync();

        context.application.suspendApiCalculationUntilNextSync();
        context.application.suspendScreenUpdatingUntilNextSync();

        try {
          await processASSETCOOutputTemplate(context, response.exceloutput);
        } finally {
          context.application.calculationMode = Excel.CalculationMode.automatic;
          await context.sync();
        }
      });
      showToast("JV consolidation calculation completed successfully!", "success");
    } catch (error) {
      console.error("Failed to run JV consolidation calculation:", error);
      showToast(error.message || "Failed to run JV consolidation calculation", "error");
    } finally {
      setIsCalculating(false);
    }
  };

  const handleSaveConfirm = async () => {
    if (!scenarioName.trim()) {
      showToast("Please enter a name for the JV consolidation scenario", "error");
      return;
    }

    setSaveAsDialogOpen(false);
    setIsSaving(true);

    try {
      const selectedLandco = landcoOptions.find(
        (item) => item.jv_iteration_id === selectedLandcoScenarioId
      );
      const selectedAssetco = assetcoOptions.find(
        (item) => item.jv_iteration_id === selectedAssetcoScenarioId
      );
      const namedranges = await getUserDefinedNamedRanges(cachedNamedItems);

      const payload = {
        namedranges,
        selected_scenarios: [
          {
            source_type: "landco_devco",
            jv_iteration_id: selectedLandco?.jv_iteration_id,
            iteration_id: selectedLandco?.iteration_id,
            scenario_name: selectedLandco?.name,
          },
          {
            source_type: "assetco_consolidation",
            jv_iteration_id: selectedAssetco?.jv_iteration_id,
            iteration_id: selectedAssetco?.iteration_id,
            scenario_name: selectedAssetco?.name,
          },
        ],
      };

      const response = await apiService.saveIteration({
        project_id: project.id,
        name: scenarioName,
        iteration_type: "jv_consolidation",
        input_json: payload,
        output_json: payload,
      });
      if (response?.iteration_id) {
        // apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
        //   console.error("Failed to normalise scenario:", normaliseError);
        //   // showToast(normaliseError.message || "Failed to normalise scenario", "error");
        // });
      }

      showToast(`JV consolidation scenario "${scenarioName}" saved successfully!`, "success");
      setScenarioName("");
      setSelectedLandcoScenarioId(null);
      setSelectedAssetcoScenarioId(null);
      setValidationErrors([]);
    } catch (error) {
      console.error("Failed to save JV consolidation scenario:", error);
      showToast(error.message || "Failed to save JV consolidation scenario", "error");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveCancel = () => {
    setSaveAsDialogOpen(false);
    setScenarioName("");
  };

  if (!project) {
    navigate("/");
    return null;
  }

  const hasWriteAccess = project.permissions?.write_access;

  return (
    <div className={styles.container}>
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
        title="Save JV Consolidation"
        hasSavedScenarios={savedScenarios.length > 0}
      />

      <Dialog open={saveAsDialogOpen} onOpenChange={(e, data) => setSaveAsDialogOpen(data.open)}>
        <DialogSurface style={{ background: "var(--bg-secondary)", color: "var(--text-primary)" }}>
          <DialogBody>
            <DialogTitle style={{ fontSize: "14px", color: "var(--text-primary)" }}>
              Save As New Scenario
            </DialogTitle>
            <DialogContent>
              <Label
                htmlFor="jv-consolidation-name"
                style={{ fontSize: "12px", color: "var(--text-primary)" }}
              >
                Scenario Name
              </Label>
              <Input
                id="jv-consolidation-name"
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
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
                onClick={handleSaveConfirm}
                disabled={!scenarioName.trim() || isSaving}
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
        scenarios={savedScenarios}
      />

      {/* Share Dialog */}
      {/* Share Scenario Dialog */}
      <ShareDialog
        open={shareDialogOpen}
        onClose={handleShareCancel}
        onShare={handleShareConfirm}
        isSharing={isSharing}
        title="Share JV Consolidation Scenario"
        users={users}
        isLoadingUsers={isLoadingUsers}
        scenarios={savedScenarios}
        initialScenario={selectedScenarioForShare}
      />

      <div className={styles.content}>
        <div className={styles.projectBanner}>
          <DataUsage24Regular style={{ fontSize: "16px" }} />
          <div className={styles.projectInfo}>
            <div className={styles.projectName}>{project.name} - JV Consolidation</div>
            <div className={styles.projectMeta}>Consolidated JV Scenario Selection</div>
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

        <div className={styles.section}>
          <div className={styles.sectionTitle}>Load Saved Scenario</div>
          <SearchableDropdown
            options={savedScenarios.map((s) => ({ value: s.id, label: s.name }))}
            value={selectedLoadScenarioId}
            onChange={(val) => setSelectedLoadScenarioId(val ? String(val) : "")}
            placeholder="Choose a scenario to load"
            disabled={savedScenarios.length === 0 || isSaving}
            style={{ marginBottom: "10px" }}
          />
          <div className={styles.actionButtons}>
            <Button
              appearance="secondary"
              size="small"
              onClick={handleLoadScenario}
              disabled={!selectedLoadScenarioId || isSaving}
            >
              Load Scenario
            </Button>
            <Button
              appearance="secondary"
              size="small"
              onClick={handleShareFromLoad}
              disabled={!selectedLoadScenarioId || isSaving}
            >
              Share
            </Button>
            {/* <Button
              appearance="secondary"
              size="small"
              onClick={handleNormalise}
              disabled={!selectedLoadScenarioId || isSaving || isNormalising}
            >
              {isNormalising ? "Normalising..." : "Normalise"}
            </Button> */}
          </div>
        </div>

        {isLoadingScenarios ? (
          <div className={styles.loadingContainer}>
            <Spinner size="small" />
            <div style={{ marginTop: "8px", fontSize: "11px", color: "var(--text-secondary)" }}>
              Loading scenarios...
            </div>
          </div>
        ) : scenarios.length === 0 ? (
          <div className={styles.emptyState}>
            <div className={styles.emptyStateIcon}>
              <DocumentTableArrowRight20Regular />
            </div>
            <div className={styles.emptyStateText}>No scenarios available</div>
            <div style={{ fontSize: "10px", opacity: 0.7 }}>
              Create LandCo/DevCo scenarios to use JV consolidation.
            </div>
          </div>
        ) : (
          <div className={styles.section}>
            <div className={styles.sectionTitle}>Select Scenarios</div>
            <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginBottom: "12px" }}>
              Choose one LandCo/DevCo and one AssetCo scenario from JV iteration data.
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "10px", minWidth: 0 }}>
              <div className={styles.dropdownGroup}>
                <Label
                  style={{
                    fontSize: "11px",
                    color: "var(--text-primary)",
                    marginBottom: "6px",
                    display: "block",
                  }}
                >
                  LandCo / DevCo
                </Label>
                <SearchableDropdown
                  options={landcoOptions.map((item) => ({
                    value: item.jv_iteration_id,
                    label: item.name,
                  }))}
                  value={selectedLandcoScenarioId ? String(selectedLandcoScenarioId) : ""}
                  onChange={(val) => setSelectedLandcoScenarioId(val ? parseInt(val, 10) : null)}
                  placeholder="Select LandCo/DevCo scenario"
                />
              </div>

              <div className={styles.dropdownGroup}>
                <Label
                  style={{
                    fontSize: "11px",
                    color: "var(--text-primary)",
                    marginBottom: "6px",
                    display: "block",
                  }}
                >
                  AssetCo Consolidation
                </Label>
                <SearchableDropdown
                  options={assetcoOptions.map((item) => ({
                    value: item.jv_iteration_id,
                    label: item.name,
                  }))}
                  value={selectedAssetcoScenarioId ? String(selectedAssetcoScenarioId) : ""}
                  onChange={(val) => setSelectedAssetcoScenarioId(val ? parseInt(val, 10) : null)}
                  placeholder="Select AssetCo Consolidation scenario"
                />
              </div>
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
                disabled={
                  isCalculating ||
                  isSaving ||
                  !selectedLandcoScenarioId ||
                  !selectedAssetcoScenarioId
                }
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
                  !selectedLandcoScenarioId ||
                  !selectedAssetcoScenarioId
                }
                className={styles.saveButton}
              >
                {isSaving ? "Saving..." : "Save JV Consolidation"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default JVConsolidation;
