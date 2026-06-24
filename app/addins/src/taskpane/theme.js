import { webDarkTheme } from "@fluentui/react-components";

/* Catppuccin Frappe — all palette colors darkened 30% from base */
const adminCssVars = {
  "--color-white": "#FFFFFF",
  "--color-dark-navy": "#222431",
  "--color-midnight-blue": "#1d1f2a",
  "--color-royal-blue": "#2e303e",
  "--color-brand-blue": "#6277a7",
  "--color-light-indigo": "#8283a9",
  "--color-delft-blue": "#45495a",
  "--color-sky-blue": "#5d879a",
  "--color-indigo": "#360164",
  "--color-ps-purple": "#8d6fa1",
  "--color-btn-primary": "#2f44a7",
  "--color-btn-primary-hover": "#243992",
  "--color-error-dark": "#a25b5c",
  "--color-error-light": "#a46b6d",
  "--color-battleship-gray": "#505568",
  "--color-lavender-mist": "#737990",
  "--bg-primary": "#222431",
  "--bg-secondary": "#14161d",
  "--bg-tertiary": "#20222b",
  "--text-primary": "#8b92ac",
  "--text-secondary": "#737990",
  "--border-color": "rgba(69, 73, 90, 0.4)",
  "--accent-color": "#8283a9",
  "--accent-hover": "#6277a7",
  "--success-color": "#6277a7",
  "--error-color": "#a25b5c",
  "--warning-color": "#8d6fa1",
  "--info-color": "#5d879a",
  "--success-bg": "rgba(98, 119, 167, 0.12)",
  "--success-text": "#8283a9",
  "--error-bg": "rgba(162, 91, 92, 0.15)",
  "--error-text": "#a46b6d",
  "--warning-bg": "rgba(141, 111, 161, 0.12)",
  "--warning-text": "#8d6fa1",
  "--info-bg": "rgba(93, 135, 154, 0.12)",
  "--info-text": "#5d879a",
  "--modal-overlay": "rgba(24, 27, 36, 0.88)",
  "--table-row-hover": "rgba(98, 119, 167, 0.08)",
  "--card-shadow": "0 2px 8px rgba(0, 0, 0, 0.25)",
  "--icon-primary": "#8283a9",
  "--icon-secondary": "#737990",
  "--icon-success": "#6277a7",
  "--icon-error": "#a46b6d",
  "--icon-warning": "#8d6fa1",
  "--icon-info": "#5d879a",
};

export const applyAdminTheme = () => {
  const root = document.documentElement;
  Object.entries(adminCssVars).forEach(([key, value]) => {
    root.style.setProperty(key, value);
  });
  root.style.colorScheme = "dark";
  document.body.style.backgroundColor = "var(--bg-primary)";
  document.body.style.color = "var(--text-primary)";
};

export const adminFluentTheme = {
  ...webDarkTheme,
  colorBrandBackground: "#6277a7",
  colorBrandBackgroundHover: "#2e303e",
  colorBrandBackgroundPressed: "#1d1f2a",
  colorBrandForeground1: "#8283a9",
  colorBrandForeground2: "#737990",
  colorBrandStroke1: "#6277a7",
  colorBrandStroke2: "#8283a9",
};
