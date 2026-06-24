import { webDarkTheme } from "@fluentui/react-components";

/* Catppuccin Frappe — soothing professional dark theme */
const adminCssVars = {
  "--color-white": "#FFFFFF",
  "--color-dark-navy": "#303446",
  "--color-midnight-blue": "#292c3c",
  "--color-royal-blue": "#414559",
  "--color-brand-blue": "#8caaee",
  "--color-light-indigo": "#babbf1",
  "--color-delft-blue": "#626880",
  "--color-sky-blue": "#85c1dc",
  "--color-indigo": "#4D018F",
  "--color-ps-purple": "#ca9ee6",
  "--color-btn-primary": "#4361ee",
  "--color-btn-primary-hover": "#3451d1",
  "--color-error-dark": "#e78284",
  "--color-error-light": "#ea999c",
  "--color-battleship-gray": "#737994",
  "--color-lavender-mist": "#a5adce",
  "--bg-primary": "#303446",
  "--bg-secondary": "#292c3c",
  "--bg-tertiary": "#414559",
  "--text-primary": "#c6d0f5",
  "--text-secondary": "#a5adce",
  "--border-color": "rgba(98, 104, 128, 0.4)",
  "--accent-color": "#babbf1",
  "--accent-hover": "#8caaee",
  "--success-color": "#8caaee",
  "--error-color": "#e78284",
  "--warning-color": "#ca9ee6",
  "--info-color": "#85c1dc",
  "--success-bg": "rgba(140, 170, 238, 0.12)",
  "--success-text": "#babbf1",
  "--error-bg": "rgba(231, 130, 132, 0.15)",
  "--error-text": "#ea999c",
  "--warning-bg": "rgba(202, 158, 230, 0.12)",
  "--warning-text": "#ca9ee6",
  "--info-bg": "rgba(133, 193, 220, 0.12)",
  "--info-text": "#85c1dc",
  "--modal-overlay": "rgba(35, 38, 52, 0.88)",
  "--table-row-hover": "rgba(140, 170, 238, 0.08)",
  "--card-shadow": "0 2px 8px rgba(0, 0, 0, 0.25)",
  "--icon-primary": "#babbf1",
  "--icon-secondary": "#a5adce",
  "--icon-success": "#8caaee",
  "--icon-error": "#ea999c",
  "--icon-warning": "#ca9ee6",
  "--icon-info": "#85c1dc",
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
  colorBrandBackground: "#8caaee",
  colorBrandBackgroundHover: "#414559",
  colorBrandBackgroundPressed: "#292c3c",
  colorBrandForeground1: "#babbf1",
  colorBrandForeground2: "#a5adce",
  colorBrandStroke1: "#8caaee",
  colorBrandStroke2: "#babbf1",
};
