import React from "react";
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
import { Save24Regular, Document24Regular } from "@fluentui/react-icons";

/**
 * Reusable save-options dialog.
 *
 * Props:
 *  - open              {boolean}   Whether the dialog is visible
 *  - onClose           {function}  Called when the user cancels
 *  - onSaveExisting    {function}  Called when "Save (Replace existing scenario)" is clicked
 *  - onSaveAsNew       {function}  Called when "Save As (Create new scenario)" is clicked
 *  - title             {string?}   Optional dialog title. Defaults to "Save Scenario"
 *  - hasSavedScenarios {boolean?}  When false, hides the "Replace existing" option.
 *                                  Defaults to true.
 */
const SaveOptionsDialog = ({
  open,
  onClose,
  onSaveExisting,
  onSaveAsNew,
  title = "Save Scenario",
  hasSavedScenarios = true,
}) => {
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
            {title}
          </DialogTitle>

          <DialogContent style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <Label style={{ fontSize: "12px", color: "var(--text-primary)" }}>
              Choose an option:
            </Label>

            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {hasSavedScenarios && (
                <Button
                  appearance="secondary"
                  onClick={onSaveExisting}
                  style={{
                    width: "100%",
                    background: "var(--bg-tertiary)",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border-color)",
                    padding: "12px",
                    justifyContent: "flex-start",
                    fontSize: "13px",
                  }}
                >
                  <Save24Regular style={{ marginRight: "8px", flexShrink: 0 }} />
                  Save (Replace existing scenario)
                </Button>
              )}

              <Button
                appearance="secondary"
                onClick={onSaveAsNew}
                style={{
                  width: "100%",
                  background: "var(--bg-tertiary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border-color)",
                  padding: "12px",
                  justifyContent: "flex-start",
                  fontSize: "13px",
                }}
              >
                <Document24Regular style={{ marginRight: "8px", flexShrink: 0 }} />
                Save As (Create new scenario)
              </Button>
            </div>
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
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
};

export default SaveOptionsDialog;
