import React, { useState } from "react";

/**
 * SearchableDropdown
 *
 * Props:
 *   options      – array of { value: string|number, label: string }
 *   value        – currently selected value (string | number | "")
 *   onChange     – (value) => void   called with the selected option's value
 *   placeholder  – string shown when nothing is selected
 *   disabled     – boolean
 *   style        – extra style for the root wrapper
 */
const SearchableDropdown = ({
  options = [],
  value,
  onChange,
  placeholder = "Search or choose...",
  disabled = false,
  style = {},
}) => {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);

  const selected = options.find((o) => String(o.value) === String(value));
  const filtered = options.filter((o) =>
    o.label.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div
      style={{ position: "relative", marginBottom: "12px", ...style }}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) {
          setOpen(false);
        }
      }}
    >
      {/* Input row */}
      <div style={{ position: "relative" }}>
        <input
          type="text"
          placeholder={selected ? selected.label : placeholder}
          value={search}
          disabled={disabled}
          onFocus={() => !disabled && setOpen(true)}
          onChange={(e) => {
            setSearch(e.target.value);
            setOpen(true);
            // clear selection if text no longer matches
            if (selected && !selected.label.toLowerCase().includes(e.target.value.toLowerCase())) {
              onChange("");
            }
          }}
          style={{
            width: "100%",
            backgroundColor: "#2b3331",
            color: disabled ? "var(--text-secondary)" : "var(--text-primary)",
            border: "1px solid var(--border-color)",
            borderRadius: open ? "6px 6px 0 0" : "6px",
            padding: "4px 32px 4px 10px",
            height: "30px",
            boxSizing: "border-box",
            outline: "none",
            fontSize: "13px",
            cursor: disabled ? "not-allowed" : "text",
          }}
        />
        {/* Chevron */}
        <span
          onClick={() => !disabled && setOpen((o) => !o)}
          style={{
            position: "absolute",
            right: "10px",
            top: "50%",
            transform: open ? "translateY(-50%) rotate(180deg)" : "translateY(-50%)",
            cursor: disabled ? "not-allowed" : "pointer",
            color: "var(--text-secondary)",
            fontSize: "10px",
            transition: "transform 0.15s",
            pointerEvents: "all",
          }}
        >
          ▼
        </span>
      </div>

      {/* Dropdown list */}
      {open && !disabled && (
        <div
          style={{
            position: "absolute",
            top: "30px",
            left: 0,
            right: 0,
            maxHeight: "180px",
            overflowY: "auto",
            backgroundColor: "#2b3331",
            border: "1px solid var(--border-color)",
            borderTop: "none",
            borderRadius: "0 0 6px 6px",
            zIndex: 200,
          }}
        >
          {filtered.length === 0 ? (
            <div
              style={{ padding: "8px 10px", fontSize: "12px", color: "var(--text-secondary)" }}
            >
              No matches found
            </div>
          ) : (
            filtered.map((option) => (
              <div
                key={option.value}
                tabIndex={0}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(option.value);
                  setSearch("");
                  setOpen(false);
                }}
                style={{
                  padding: "6px 10px",
                  fontSize: "12px",
                  color: "var(--text-primary)",
                  cursor: "pointer",
                  backgroundColor:
                    String(value) === String(option.value)
                      ? "var(--bg-tertiary)"
                      : "transparent",
                  borderBottom: "1px solid var(--border-color)",
                }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.backgroundColor = "var(--bg-tertiary)")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.backgroundColor =
                    String(value) === String(option.value)
                      ? "var(--bg-tertiary)"
                      : "transparent")
                }
              >
                {option.label}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};

export default SearchableDropdown;
