import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogSurface,
  DialogBody,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Label,
} from "@fluentui/react-components";
import { Warning24Regular } from "@fluentui/react-icons";

/**
 * Reusable overwrite-scenario dialog.
 *
 * Props:
 *  - open        {boolean}   Whether the dialog is visible
 *  - onClose     {function}  Called when the user cancels
 *  - onConfirm   {function}  Called with the selected scenario object when confirmed
 *  - isSaving    {boolean}   Shows "Saving..." and disables button while API call runs
 *  - scenarios   {array}     Scenarios to choose from: [{ id, name }]
 *  - warningText {string?}   Optional custom warning. Defaults to generic message.
 */
const OverwriteDialog = ({
  open,
  onClose,
  onConfirm,
  isSaving = false,
  scenarios = [],
  warningText,
}) => {
  const [search, setSearch] = useState("");
  const [selectedScenario, setSelectedScenario] = useState(null);

  useEffect(() => {
    if (open) {
      setSearch("");
      setSelectedScenario(null);
    }
  }, [open]);

  const filtered = scenarios.filter((s) =>
    s.name.toLowerCase().includes(search.toLowerCase())
  );

  const defaultWarning = selectedScenario
    ? `This will replace "${selectedScenario.name}" with the current data. This action cannot be undone.`
    : "";

  const handleConfirm = () => {
    if (!selectedScenario || isSaving) return;
    onConfirm(selectedScenario);
  };

  return (
    <Dialog open={open} onOpenChange={(e, data) => { if (!data.open) onClose(); }}>
      <DialogSurface
        style={{
          background: "var(--bg-secondary)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-color)",
        }}
      >
        <DialogBody>
          <DialogTitle
            style={{
              fontSize: "14px",
              fontWeight: "600",
              color: "var(--text-primary)",
            }}
          >
            Select Scenario to Overwrite
          </DialogTitle>

          <DialogContent
            style={{ display: "flex", flexDirection: "column", gap: "10px" }}
          >
            <Label style={{ fontSize: "12px", color: "var(--text-primary)" }}>
              Available Scenarios:
            </Label>

            {/* Search input */}
            <input
              type="text"
              placeholder="Search scenarios..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                width: "100%",
                backgroundColor: "#1e2a28",
                color: "var(--text-primary)",
                border: "1px solid var(--border-color)",
                borderRadius: "6px",
                padding: "6px 10px",
                fontSize: "13px",
                boxSizing: "border-box",
                outline: "none",
              }}
            />

            {/* Scrollable scenario list */}
            <div
              style={{
                maxHeight: "200px",
                overflowY: "auto",
                border: "1px solid var(--border-color)",
                borderRadius: "6px",
                backgroundColor: "#1e2a28",
              }}
            >
              {scenarios.length === 0 ? (
                <div
                  style={{
                    padding: "12px",
                    fontSize: "13px",
                    color: "var(--text-secondary)",
                    textAlign: "center",
                  }}
                >
                  No scenarios available
                </div>
              ) : filtered.length === 0 ? (
                <div
                  style={{
                    padding: "10px 12px",
                    fontSize: "13px",
                    color: "var(--text-secondary)",
                  }}
                >
                  No scenarios match
                </div>
              ) : (
                filtered.map((s) => {
                  const isSelected = selectedScenario?.id === s.id;
                  return (
                    <div
                      key={s.id}
                      onClick={() => setSelectedScenario(isSelected ? null : s)}
                      style={{
                        padding: "9px 12px",
                        fontSize: "13px",
                        fontWeight: isSelected ? "600" : "400",
                        color: isSelected ? "#ffffff" : "var(--text-primary)",
                        cursor: "pointer",
                        borderBottom: "1px solid var(--border-color)",
                        backgroundColor: isSelected
                          ? "var(--error-bg)"
                          : "transparent",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        transition: "background-color 0.1s",
                      }}
                      onMouseEnter={(e) => {
                        if (!isSelected)
                          e.currentTarget.style.backgroundColor = "var(--bg-tertiary)";
                      }}
                      onMouseLeave={(e) => {
                        if (!isSelected)
                          e.currentTarget.style.backgroundColor = "transparent";
                      }}
                    >
                      <span style={{ flex: 1 }}>{s.name}</span>
                      {isSelected && (
                        <span style={{ fontSize: "11px", opacity: 0.9 }}>✓</span>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {/* Warning box */}
            {selectedScenario && (
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "8px",
                  padding: "10px 12px",
                  background: "var(--error-bg)",
                  border: "1px solid var(--error-text)",
                  borderRadius: "6px",
                  fontSize: "12px",
                  color: "var(--error-text)",
                }}
              >
                <Warning24Regular style={{ fontSize: "16px", flexShrink: 0, marginTop: "1px" }} />
                <span>{warningText || defaultWarning}</span>
              </div>
            )}
          </DialogContent>

          <DialogActions>
            <Button
              size="small"
              appearance="secondary"
              onClick={onClose}
              style={{
                background: "var(--bg-tertiary)",
                color: "var(--text-primary)",
                border: "1px solid var(--border-color)",
              }}
            >
              Cancel
            </Button>
            <Button
              size="small"
              appearance="primary"
              onClick={handleConfirm}
              disabled={!selectedScenario || isSaving}
              style={{
                background: selectedScenario ? "var(--error-bg)" : undefined,
                color: "white",
                border: selectedScenario ? "1px solid var(--error-text)" : undefined,
              }}
            >
              {isSaving ? "Saving..." : "Overwrite"}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
};

export default OverwriteDialog;
