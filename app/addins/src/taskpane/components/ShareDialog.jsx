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
  Spinner,
} from "@fluentui/react-components";
import SearchableDropdown from "./SearchableDropdown";

/**
 * Reusable share dialog component.
 *
 * Props:
 *  - open           {boolean}   Whether the dialog is visible
 *  - onClose        {function}  Called when the user dismisses / cancels
 *  - onShare        {function}  Called with (user, scenario?) when the user confirms
 *  - isSharing      {boolean}   Shows "Sharing…" and disables the button while the API call runs
 *  - title          {string}    Dialog heading
 *  - users          {array}     User objects { id, first_name, last_name, email, username }
 *  - isLoadingUsers {boolean}   Shows a spinner while users are being fetched
 *  - scenarios      {array?}    Optional list of scenarios { id, name }.
 *                               When supplied, the dialog adds a scenario picker above the user list.
 *  - initialScenario{object?}   Pre-selected scenario object (used with scenarios prop)
 */
const ShareDialog = ({
  open,
  onClose,
  onShare,
  isSharing = false,
  title = "Share Scenario",
  users = [],
  isLoadingUsers = false,
  scenarios = null,
  initialScenario = null,
}) => {
  const [userSearch, setUserSearch] = useState("");
  const [selectedUser, setSelectedUser] = useState(null);
  const [selectedScenario, setSelectedScenario] = useState(null);

  // Sync internal scenario state when dialog opens or initialScenario changes
  useEffect(() => {
    if (open) {
      setSelectedScenario(initialScenario || null);
      setUserSearch("");
      setSelectedUser(null);
    }
  }, [open, initialScenario]);

  const filteredUsers = users.filter((u) => {
    const label =
      u.first_name && u.last_name
        ? `${u.first_name} ${u.last_name} ${u.email || u.username}`
        : u.email || u.username || "";
    return label.toLowerCase().includes(userSearch.toLowerCase());
  });

  const canShare =
    selectedUser && (!scenarios || selectedScenario) && !isSharing;

  const handleConfirm = () => {
    if (!canShare) return;
    onShare(selectedUser, scenarios ? selectedScenario : undefined);
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
            {title}
          </DialogTitle>

          <DialogContent
            style={{ display: "flex", flexDirection: "column", gap: "12px" }}
          >
            {/* Scenario — read-only if pre-selected, picker if not */}
            {scenarios && initialScenario ? (
              <>
                <Label style={{ fontSize: "12px", color: "var(--text-primary)" }}>
                  Scenario:
                </Label>
                <div
                  style={{
                    padding: "6px 10px",
                    fontSize: "13px",
                    color: "var(--text-primary)",
                    background: "var(--bg-tertiary)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "6px",
                  }}
                >
                  {initialScenario.name}
                </div>
              </>
            ) : scenarios ? (
              <>
                <Label style={{ fontSize: "12px", color: "var(--text-primary)" }}>
                  Select Scenario to Share:
                </Label>
                <SearchableDropdown
                  options={scenarios.map((s) => ({ value: s.id, label: s.name }))}
                  value={selectedScenario ? String(selectedScenario.id) : ""}
                  onChange={(val) => {
                    const s = scenarios.find((sc) => String(sc.id) === String(val));
                    setSelectedScenario(s || null);
                  }}
                  placeholder="Choose a scenario"
                />
              </>
            ) : null}

            {/* User picker */}
            <Label style={{ fontSize: "12px", color: "var(--text-primary)" }}>
              Select User to Share With:
            </Label>

            {isLoadingUsers ? (
              <div
                style={{
                  padding: "12px",
                  textAlign: "center",
                  color: "var(--text-secondary)",
                }}
              >
                <Spinner size="small" label="Loading users..." />
              </div>
            ) : users.length === 0 ? (
              <div
                style={{
                  padding: "12px",
                  textAlign: "center",
                  color: "var(--text-secondary)",
                  fontSize: "12px",
                }}
              >
                No users available
              </div>
            ) : (
              <>
                {/* Search input — avoids SearchableDropdown clipping inside Dialog */}
                <input
                  type="text"
                  placeholder="Search users..."
                  value={userSearch}
                  onChange={(e) => setUserSearch(e.target.value)}
                  style={{
                    width: "100%",
                    backgroundColor: "#2b3331",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "6px",
                    padding: "6px 10px",
                    fontSize: "13px",
                    boxSizing: "border-box",
                    outline: "none",
                  }}
                />

                {/* Scrollable user list */}
                <div
                  style={{
                    maxHeight: "180px",
                    overflowY: "auto",
                    border: "1px solid var(--border-color)",
                    borderRadius: "6px",
                    backgroundColor: "#2b3331",
                  }}
                >
                  {filteredUsers.length === 0 ? (
                    <div
                      style={{
                        padding: "10px 12px",
                        fontSize: "13px",
                        color: "var(--text-secondary)",
                      }}
                    >
                      No users match
                    </div>
                  ) : (
                    filteredUsers.map((u) => {
                      const label =
                        u.first_name && u.last_name
                          ? `${u.first_name} ${u.last_name} (${u.email || u.username})`
                          : u.email || u.username;
                      const isSelected = selectedUser?.id === u.id;
                      return (
                        <div
                          key={u.id}
                          onClick={() => setSelectedUser(isSelected ? null : u)}
                          style={{
                            padding: "8px 12px",
                            fontSize: "13px",
                            color: "var(--text-primary)",
                            cursor: "pointer",
                            borderBottom: "1px solid var(--border-color)",
                            backgroundColor: isSelected
                              ? "var(--accent-hover)"
                              : "transparent",
                            display: "flex",
                            alignItems: "center",
                            gap: "8px",
                          }}
                          onMouseEnter={(e) => {
                            if (!isSelected)
                              e.currentTarget.style.backgroundColor =
                                "var(--bg-tertiary)";
                          }}
                          onMouseLeave={(e) => {
                            if (!isSelected)
                              e.currentTarget.style.backgroundColor =
                                "transparent";
                          }}
                        >
                          <span style={{ flex: 1 }}>{label}</span>
                          {isSelected && (
                            <span style={{ fontSize: "11px", opacity: 0.8 }}>
                              ✓
                            </span>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </>
            )}

            <div
              style={{
                padding: "6px 8px",
                backgroundColor: "var(--bg-tertiary)",
                borderRadius: "4px",
                fontSize: "11px",
                color: "var(--text-secondary)",
              }}
            >
              Shared scenarios are read-only. Recipients can view and load but
              cannot modify them.
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
            <Button
              size="small"
              appearance="primary"
              onClick={handleConfirm}
              disabled={!canShare}
              style={{ background: "var(--accent-hover)", color: "white" }}
            >
              {isSharing ? "Sharing..." : "Share"}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
};

export default ShareDialog;
