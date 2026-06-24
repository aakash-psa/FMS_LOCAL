import { webDarkTheme } from "@fluentui/react-components";

/* Catppuccin Mocha — definitive dark theme for FMS Add-ins */
const adminCssVars = {
  "--color-white": "#FFFFFF",
  "--color-dark-navy": "#1e1e2e",        // Mocha Base
  "--color-midnight-blue": "#181825",    // Mocha Mantle
  "--color-royal-blue": "#313244",       // Mocha Surface0
  "--color-brand-blue": "#89b4fa",       // Mocha Blue
  "--color-light-indigo": "#b4befe",     // Mocha Lavender
  "--color-delft-blue": "#6c7086",       // Mocha Overlay0
  "--color-sky-blue": "#74c7ec",         // Mocha Sapphire
  "--color-indigo": "#4D018F",
  "--color-ps-purple": "#cba6f7",        // Mocha Mauve
  "--color-btn-primary": "#45475a",      // Mocha Surface1 — dark button
  "--color-btn-primary-hover": "#585b70", // Mocha Surface2 — hover lift
  "--color-error-dark": "#f38ba8",       // Mocha Red
  "--color-error-light": "#eba0ac",      // Mocha Maroon
  "--color-battleship-gray": "#9399b2",  // Mocha Overlay2
  "--color-lavender-mist": "#a6adc8",    // Mocha Subtext0
  "--bg-primary": "#1e1e2e",
  "--bg-secondary": "#181825",
  "--bg-tertiary": "#313244",
  "--text-primary": "#FFFFFF",
  "--text-secondary": "#cdd6f4",         // Mocha Text — secondary
  "--border-color": "rgba(108, 112, 134, 0.4)",
  "--accent-color": "#b4befe",
  "--accent-hover": "#89b4fa",
  "--success-color": "#a6e3a1",          // Mocha Green
  "--error-color": "#f38ba8",
  "--warning-color": "#fab387",          // Mocha Peach
  "--info-color": "#74c7ec",
  "--success-bg": "rgba(166, 227, 161, 0.12)",
  "--success-text": "#a6e3a1",
  "--error-bg": "rgba(243, 139, 168, 0.15)",
  "--error-text": "#eba0ac",
  "--warning-bg": "rgba(250, 179, 135, 0.12)",
  "--warning-text": "#fab387",
  "--info-bg": "rgba(116, 199, 236, 0.12)",
  "--info-text": "#74c7ec",
  "--modal-overlay": "rgba(17, 17, 27, 0.88)",
  "--table-row-hover": "rgba(137, 180, 250, 0.08)",
  "--card-shadow": "0 2px 8px rgba(0, 0, 0, 0.35)",
  "--icon-primary": "#b4befe",
  "--icon-secondary": "#a6adc8",
  "--icon-success": "#a6e3a1",
  "--icon-error": "#eba0ac",
  "--icon-warning": "#fab387",
  "--icon-info": "#74c7ec",
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
  colorBrandBackground: "#45475a",
  colorBrandBackgroundHover: "#585b70",
  colorBrandBackgroundPressed: "#181825",
  colorBrandForeground1: "#b4befe",
  colorBrandForeground2: "#a6adc8",
  colorBrandStroke1: "#89b4fa",
  colorBrandStroke2: "#b4befe",
};
