import React, { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Card,
  Badge,
  makeStyles,
  Button,
  Label,
  Dialog,
  DialogSurface,
  DialogTitle,
  DialogBody,
  DialogActions,
  DialogContent,
  Input,
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
  DocumentTableArrowRight24Regular,
  Calculator24Regular,
  Save24Regular,
  ArrowLeft24Regular,
  Share24Regular,
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
  backButton: {
    marginBottom: "16px",
    background: "var(--bg-secondary)",
    color: "var(--text-primary)",
    border: "1px solid var(--border-color)",
  },
  actionsGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "12px",
    marginTop: "24px",
  },
  actionCard: {
    marginTop: "24px",
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
    marginTop: "24px",
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
    color: "var(--accent-hover)",
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
  actionTitle: {
    fontSize: "14px",
    fontWeight: "600",
    marginBottom: "4px",
  },
  actionDescription: {
    fontSize: "11px",
    color: "var(--text-secondary)",
  },
  infoBox: {
    background: "var(--bg-secondary)",
    padding: "16px",
    borderRadius: "8px",
    border: "1px solid var(--border-color)",
    marginTop: "16px",
  },
  infoTitle: {
    fontSize: "14px",
    fontWeight: "600",
    marginBottom: "8px",
    color: "var(--text-primary)",
  },
  infoText: {
    fontSize: "13px",
    color: "var(--text-secondary)",
    lineHeight: "1.6",
  },
  baseFileCard: {
    marginTop: "16px",
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
    marginTop: "16px",
    background: "var(--bg-secondary)",
    padding: "16px",
    borderRadius: "8px",
    border: "1px solid var(--border-color)",
  },
  dropdownLabel: {
    fontSize: "12px",
    color: "var(--text-primary)",
    marginBottom: "8px",
    display: "block",
  },
  select: {
    width: "100%",
    fontSize: "12px",
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
  sourceGroup: {
    marginTop: "10px",
    padding: "10px",
    border: "1px solid var(--border-color)",
    borderRadius: "6px",
    background: "var(--bg-primary)",
  },
  sourceGroupTitle: {
    fontSize: "12px",
    fontWeight: "600",
    color: "var(--text-primary)",
    marginBottom: "8px",
  },
  helperText: {
    fontSize: "11px",
    color: "var(--text-secondary)",
    marginTop: "8px",
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

const Consolidation = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const styles = useStyles();
  const project = location.state?.project;
  const { apiService } = useAuth();

  const [isCalculating, setIsCalculating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [hasTemplateSheets, setHasTemplateSheets] = useState(false);
  const [isLoadingSourceData, setIsLoadingSourceData] = useState(false);
  const [sourceData, setSourceData] = useState(null);
  const [selectedSourceByType, setSelectedSourceByType] = useState({
    landco_devco: "",
    assetco_consolidation: "",
    jv_consolidation: "",
  });
  const [savedScenarios, setSavedScenarios] = useState([]);
  const [selectedLoadScenarioId, setSelectedLoadScenarioId] = useState("");
  const [saveOptionsDialogOpen, setSaveOptionsDialogOpen] = useState(false);
  const [saveAsDialogOpen, setSaveAsDialogOpen] = useState(false);
  const [selectScenarioForOverwriteOpen, setSelectScenarioForOverwriteOpen] = useState(false);

  const [scenarioName, setScenarioName] = useState("");
  const [toasts, setToasts] = useState([]);
  const [shareDialogOpen, setShareDialogOpen] = useState(false);

  const [users, setUsers] = useState([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [isSharing, setIsSharing] = useState(false);
  const [isNormalising, setIsNormalising] = useState(false);
  const [selectedScenarioForShare, setSelectedScenarioForShare] = useState(null);
  const [cachedNamedItems, setCachedNamedItems] = useState(null);

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

  useEffect(() => {
    const checkTemplateSheets = async () => {
      try {
        await Excel.run(async (context) => {
          const sheets = context.workbook.worksheets;
          sheets.load("items/name");
          await context.sync();

          const sheetNames = sheets.items.map((sheet) => sheet.name);
          const requiredTemplates = ["AC - CFS Template", "DC - CFS Template", "LC - CFS Template", "Conso - CFS Template"];
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
    if (!project?.id) return;

    const loadSourceData = async () => {
      setIsLoadingSourceData(true);
      try {
        const response = await apiService.fetchProjectConsolidationScenarios(project.id, {});
        setSourceData(response || null);
      } catch (error) {
        console.error("Failed to load consolidation source data:", error);
        showToast(error.message || "Failed to load consolidation source data", "error");
      } finally {
        setIsLoadingSourceData(false);
      }
    };

    loadSourceData();
  }, [project?.id]);

  useEffect(() => {
    if (!project?.id) return;

    const fetchSavedScenarios = async () => {
      try {
        const response = await apiService.fetchProjectScenarios(project.id, {
          iteration_type: "project_consolidation",
        });
        setSavedScenarios(response.scenarios || []);
      } catch (error) {
        console.error("Failed to fetch project consolidation scenarios:", error);
      }
    };

    fetchSavedScenarios();
  }, [project?.id]);

  useEffect(() => {
    const loadAllNamedItems = async () => {
      try {
        const refs = await buildNamedItemCache(["m.mastersheet", "m.jv"]);
        setCachedNamedItems(refs);
      } catch (err) {
        console.error("Failed to pre-load named items:", err);
      }
    };
    loadAllNamedItems();
  }, []);

  const sourceOptionsByType = useMemo(() => {
    if (!sourceData) {
      return {
        landco_devco: [],
        assetco_consolidation: [],
        jv_consolidation: [],
      };
    }

    return {
      landco_devco: (sourceData.consolidated_iteration?.landco_devco || []).map((item) => ({
        id: `consolidated_landco_devco_${item.consolidated_iteration_id || item.iteration_id}`,
        label: `${item.name}`,
        data: item,
        source_group: "consolidated_iteration",
        source_type: "landco_devco",
      })),
      assetco_consolidation: (sourceData.consolidated_iteration?.assetco_consolidation || []).map(
        (item) => ({
          id: `consolidated_assetco_consolidation_${item.consolidated_iteration_id || item.iteration_id}`,
          label: `${item.name}`,
          data: item,
          source_group: "consolidated_iteration",
          source_type: "assetco_consolidation",
        })
      ),
      jv_consolidation: (
        sourceData.consolidated_iteration?.jv_consolidation ||
        sourceData.jv_iteration?.jv_consolidation ||
        []
      ).map((item) => ({
        id: `jv_jv_consolidation_${item.consolidated_iteration_id || item.jv_iteration_id || item.iteration_id}`,
        label: `${item.name}`,
        data: item,
        source_group: item.consolidated_iteration_id ? "consolidated_iteration" : "jv_iteration",
        source_type: "jv_consolidation",
      })),
    };
  }, [sourceData]);

  const sourceOptions = useMemo(
    () => [
      ...sourceOptionsByType.landco_devco,
      ...sourceOptionsByType.assetco_consolidation,
      ...sourceOptionsByType.jv_consolidation,
    ],
    [sourceOptionsByType]
  );

  const buildSelectionReference = (item) => {
    if (!item || typeof item !== "object") {
      return null;
    }

    if (item.consolidated_iteration_id) {
      return { consolidated_iteration_id: item.consolidated_iteration_id };
    }

    if (item.jv_iteration_id) {
      return { jv_iteration_id: item.jv_iteration_id };
    }

    if (item.iteration_id) {
      return { iteration_id: item.iteration_id };
    }

    return null;
  };

  const doesSelectionReferenceMatch = (option, selectionReference) => {
    if (!selectionReference || typeof selectionReference !== "object") {
      return false;
    }

    const optionData = option?.data || {};

    if (selectionReference.consolidated_iteration_id) {
      return optionData.consolidated_iteration_id === selectionReference.consolidated_iteration_id;
    }

    if (selectionReference.jv_iteration_id) {
      return optionData.jv_iteration_id === selectionReference.jv_iteration_id;
    }

    if (selectionReference.iteration_id) {
      return optionData.iteration_id === selectionReference.iteration_id;
    }

    return false;
  };

  const selectedSourceDataByType = useMemo(
    () => [
      ...sourceOptionsByType.landco_devco
        .filter((option) => option.id === selectedSourceByType.landco_devco)
        .map((option) => ({ ...option.data, source_type: "landco_devco" })),
      ...sourceOptionsByType.assetco_consolidation
        .filter((option) => option.id === selectedSourceByType.assetco_consolidation)
        .map((option) => ({ ...option.data, source_type: "assetco_consolidation" })),
      ...sourceOptionsByType.jv_consolidation
        .filter((option) => option.id === selectedSourceByType.jv_consolidation)
        .map((option) => ({ ...option.data, source_type: "jv_consolidation" })),
    ],
    [selectedSourceByType, sourceOptionsByType]
  );

  const selectedSourceIds = useMemo(
    () => selectedSourceDataByType.map(buildSelectionReference).filter(Boolean),
    [selectedSourceDataByType]
  );

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
      const loadedSelection = scenario?.input_json?.source_selection?.selected_id;
      const loadedSelections = scenario?.input_json?.source_selection?.selected_ids;
      const inputData = scenario?.input_json?.namedRanges;
      const outputData = scenario?.output_json;

      if (Array.isArray(loadedSelections) && loadedSelections.length > 0) {
        const nextSelectedByType = {
          landco_devco: "",
          assetco_consolidation: "",
          jv_consolidation: "",
        };

        loadedSelections.forEach((selectionReference) => {
          const matched = sourceOptions.find((item) => {
            if (typeof selectionReference === "string") {
              return item.id === selectionReference;
            }

            return doesSelectionReferenceMatch(item, selectionReference);
          });

          if (matched && !nextSelectedByType[matched.source_type]) {
            nextSelectedByType[matched.source_type] = matched.id;
          }
        });

        const hasAnySelection = Object.values(nextSelectedByType).some(Boolean);
        setSelectedSourceByType(nextSelectedByType);

        if (!hasAnySelection) {
          showToast(
            "Scenario loaded but saved source selections are not available in current source list",
            "error"
          );
        }
      } else if (loadedSelection && sourceOptions.some((item) => item.id === loadedSelection)) {
        const matched = sourceOptions.find((item) => item.id === loadedSelection);
        if (matched) {
          setSelectedSourceByType((prev) => ({
            ...prev,
            [matched.source_type]: matched.id,
          }));
        }
      }

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

          await processASSETCOOutputTemplate(context, outputData);
        } finally {
          context.application.calculationMode = Excel.CalculationMode.automatic;
          await context.sync();
        }
      });

      showToast(`Loaded scenario "${scenario?.name || ""}" successfully`, "success");
    } catch (error) {
      console.error("Failed to load project consolidation scenario:", error);
      showToast(error.message || "Failed to load project consolidation scenario", "error");
    }
  };

  const validateSourceSelections = () => {
    const typeConfig = [
      { key: "landco_devco", label: "LandCo/DevCo" },
      { key: "assetco_consolidation", label: "AssetCo Consolidation" },
      { key: "jv_consolidation", label: "JV Consolidation" },
    ];

    for (const config of typeConfig) {
      const options = sourceOptionsByType[config.key] || [];
      if (options.length === 0) {
        continue;
      }
      const selectedId = selectedSourceByType[config.key];
      if (!selectedId || !options.some((option) => option.id === selectedId)) {
        showToast(`Please select at least one scenario from ${config.label}`, "error");
        return false;
      }
    }
    return true;
  };

  async function getUserDefinedNamedRanges(preloadedItems = null) {
    return readNamedRangesByPrefixes(["m.mastersheet", "m.jv"], preloadedItems);
  }

  const handleSourceSelect = (sourceType, sourceId) => {
    setSelectedSourceByType((prev) => ({
      ...prev,
      [sourceType]: sourceId,
    }));
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
    const templateSheetName = "Conso - CFS Template";
    const cashflowSheetName = "Conso - CFS";

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
    setIsCalculating(true);
    try {
      if (!validateSourceSelections()) {
        return;
      }
      const namedRanges = await getUserDefinedNamedRanges(cachedNamedItems);
      const inputData = {
        calculation_module: "project_consolidation",
        project_id: project.id,
        input_json: {
          namedRanges,
          source_selection: {
            selected_ids: selectedSourceIds,
            selections_by_type: selectedSourceDataByType,
          },
        },
      };
      const response = await apiService.calculateConsolidated(inputData);

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

      showToast("Project consolidation completed successfully!", "success");
    } catch (error) {
      console.error("Failed to run consolidation:", error);
      showToast(error.message || "Failed to run consolidation", "error");
    } finally {
      setIsCalculating(false);
    }
  };

  const handleSaveScenario = () => {
    if (!hasWriteAccess) {
      showToast("Write access required to save scenarios", "error");
      return;
    }
    if (!validateSourceSelections()) return;
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
  const handleSaveOptionsCancel = () => setSaveOptionsDialogOpen(false);
  const handleSaveAsCancel = () => {
    setSaveAsDialogOpen(false);
    setScenarioName("");
  };
  const handleSelectScenarioCancel = () => {
    setSelectScenarioForOverwriteOpen(false);
  };

  const handleConfirmOverwrite = async (scenario) => {
    setSelectScenarioForOverwriteOpen(false);
    setIsSaving(true);
    const namedRanges = await getUserDefinedNamedRanges(cachedNamedItems);
    try {
      const inputData = {
        iteration_type: "project_consolidation",
        project_id: project.id,
        namedRanges,
        source_selection: {
          selected_ids: selectedSourceIds,
          selections_by_type: selectedSourceDataByType,
        },
      };
      const response = await apiService.saveIteration({
        project_id: project.id,
        iteration_id: scenario.id,
        name: scenario.name,
        iteration_type: "project_consolidation",
        input_json: inputData,
      });
      if (response?.iteration_id) {
        // apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
        //   console.error("Failed to normalise scenario:", normaliseError);
        //   // showToast(normaliseError.message || "Failed to normalise scenario", "error");
        // });
      }
      showToast(`Scenario "${scenario.name}" updated successfully!`, "success");
      const res = await apiService.fetchProjectScenarios(project.id, {
        iteration_type: "project_consolidation",
      });
      setSavedScenarios(res.scenarios || []);
    } catch (error) {
      showToast(error.message || "Failed to overwrite scenario", "error");


    } finally {
      setIsSaving(false);
    }
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

  const handleSaveConfirm = async () => {
    if (!scenarioName.trim()) {
      showToast("Please enter a scenario name", "error");
      return;
    }

    if (!validateSourceSelections()) {
      return;
    }

    setSaveAsDialogOpen(false);
    setIsSaving(true);

    const namedRanges = await getUserDefinedNamedRanges(cachedNamedItems);

    try {
      const inputData = {
        iteration_type: "project_consolidation",
        project_id: project.id,
        namedRanges,
        source_selection: {
          selected_ids: selectedSourceIds,
          selections_by_type: selectedSourceDataByType,
        },
      };

      const response = await apiService.saveIteration({
        project_id: project.id,
        name: scenarioName.trim(),
        iteration_type: "project_consolidation",
        input_json: inputData,
      });
      if (response?.iteration_id) {
        // apiService.normaliseIteration(response.iteration_id).catch((normaliseError) => {
        //   console.error("Failed to normalise scenario:", normaliseError);
        //   // showToast(normaliseError.message || "Failed to normalise scenario", "error");
        // });
      }

      showToast(`Scenario "${scenarioName.trim()}" saved successfully!`, "success");
      setScenarioName("");

      const response2 = await apiService.fetchProjectScenarios(project.id, {
        iteration_type: "project_consolidation",
      });
      setSavedScenarios(response2.scenarios || []);
    } catch (error) {
      console.error("Failed to save project consolidation scenario:", error);
      showToast(error.message || "Failed to save project consolidation scenario", "error");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveCancel = () => {
    setSaveAsDialogOpen(false);
    setScenarioName("");
  };

  if (!project) {
    return (
      <div className={styles.container}>
        <div className={styles.content}>
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
        {/* Project Banner */}
        <div className={styles.projectBanner}>
          <DocumentTableArrowRight24Regular />
          <div className={styles.projectInfo}>
            <div className={styles.projectName}>{project.name} - Project Consolidation</div>
            <div className={styles.projectMeta}>Complete Project View</div>
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
            <Folder24Regular />
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
        </Card>

        <div className={styles.section}>
          <div className={styles.sectionTitle}>Load Saved Scenario</div>
          <SearchableDropdown
            options={savedScenarios.map((s) => ({ value: s.id, label: s.name }))}
            value={selectedLoadScenarioId}
            onChange={(val) => setSelectedLoadScenarioId(val ? String(val) : "")}
            placeholder="Choose a scenario to load"
            disabled={savedScenarios.length === 0 || isCalculating}
          />
          <div className={styles.actionButtons}>
            <Button
              appearance="secondary"
              size="small"
              onClick={handleLoadScenario}
              disabled={!selectedLoadScenarioId || isCalculating}
            >
              Load Scenario
            </Button>
            <Button
              appearance="secondary"
              size="small"
              onClick={handleShareFromLoad}
              disabled={!selectedLoadScenarioId || isCalculating}
            >
              Share
            </Button>
            {/* <Button
              appearance="secondary"
              size="small"
              onClick={handleNormalise}
              disabled={!selectedLoadScenarioId || isCalculating || isNormalising}
            >
              {isNormalising ? "Normalising..." : "Normalise"}
            </Button> */}
          </div>
        </div>

        {isLoadingSourceData ? (
          <div className={styles.dropdownSection}>
            <Label className={styles.dropdownLabel}>Select Consolidation Source</Label>
            <div className={styles.helperText}>Loading consolidation sources...</div>
          </div>
        ) : (
          <div className={styles.dropdownSection}>
            <Label className={styles.dropdownLabel}>Select Consolidation Source</Label>
            <div className={styles.sourceGroup}>
              <div className={styles.sourceGroupTitle}>LandCo/DevCo</div>
              {sourceOptionsByType.landco_devco.length === 0 ? (
                <div className={styles.helperText}>No scenarios available</div>
              ) : (
                <SearchableDropdown
                  options={sourceOptionsByType.landco_devco.map((o) => ({
                    value: o.id,
                    label: o.label,
                  }))}
                  value={selectedSourceByType.landco_devco || ""}
                  onChange={(val) => handleSourceSelect("landco_devco", val || "")}
                  placeholder="Choose one scenario"
                  disabled={isCalculating}
                />
              )}
            </div>

            <div className={styles.sourceGroup}>
              <div className={styles.sourceGroupTitle}>AssetCo Consolidation</div>
              {sourceOptionsByType.assetco_consolidation.length === 0 ? (
                <div className={styles.helperText}>No scenarios available</div>
              ) : (
                <SearchableDropdown
                  options={sourceOptionsByType.assetco_consolidation.map((o) => ({
                    value: o.id,
                    label: o.label,
                  }))}
                  value={selectedSourceByType.assetco_consolidation || ""}
                  onChange={(val) => handleSourceSelect("assetco_consolidation", val || "")}
                  placeholder="Choose one scenario"
                  disabled={isCalculating}
                />
              )}
            </div>

            <div className={styles.sourceGroup}>
              <div className={styles.sourceGroupTitle}>JV Consolidation</div>
              {sourceOptionsByType.jv_consolidation.length === 0 ? (
                <div className={styles.helperText}>No scenarios available</div>
              ) : (
                <SearchableDropdown
                  options={sourceOptionsByType.jv_consolidation.map((o) => ({
                    value: o.id,
                    label: o.label,
                  }))}
                  value={selectedSourceByType.jv_consolidation || ""}
                  onChange={(val) => handleSourceSelect("jv_consolidation", val || "")}
                  placeholder="Choose one scenario"
                  disabled={isCalculating}
                />
              )}
            </div>

            <div className={styles.helperText}>Select one scenario from each available type.</div>
          </div>
        )}

        <div className={styles.actionsGrid}>
          <Card
            className={styles.actionCard}
            onClick={!isCalculating ? handleCalculations : undefined}
            style={isCalculating ? { opacity: 0.6, cursor: "wait" } : {}}
          >
            <div className={styles.actionIcon}>
              <Calculator24Regular />
            </div>
            <div className={styles.actionTitle}>
              {isCalculating ? "Consolidating..." : "Run Calculations"}
            </div>
            <div className={styles.actionDescription}>
              {isCalculating
                ? "Processing complete project consolidation..."
                : "Generate consolidated view across all models"}
            </div>
          </Card>

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
                  ? "Save current project consolidation scenario"
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
        title="Save Project Consolidation Scenario"
        hasSavedScenarios={savedScenarios.length > 0}
      />

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
                htmlFor="projectConsolidationScenarioName"
                style={{ fontSize: "14px", fontWeight: "500", color: "var(--text-primary)" }}
                required
              >
                Scenario Name
              </Label>
              <Input
                id="projectConsolidationScenarioName"
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
                placeholder="Enter scenario name"
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
                onClick={handleSaveConfirm}
                disabled={!scenarioName.trim()}
                style={{
                  background: "var(--accent-hover)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--accent-hover)",
                }}
              >
                Save Scenario
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
        title="Share Consolidation Scenario"
        users={users}
        isLoadingUsers={isLoadingUsers}
        scenarios={savedScenarios}
        initialScenario={selectedScenarioForShare}
      />
    </div>
  );
};

export default Consolidation;
