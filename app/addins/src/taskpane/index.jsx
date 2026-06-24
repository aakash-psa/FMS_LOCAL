import * as React from "react";
import { createRoot } from "react-dom/client";
import App from "./components/App";
import { FluentProvider, webDarkTheme } from "@fluentui/react-components";
import { AuthProvider } from "../msal/AuthProvider";
import { adminFluentTheme, applyAdminTheme } from "./theme";
import SplashScreen from "./components/SplashScreen";

/* global document, Office, module, require */

const title = "FMS-DEV Addins";

const rootElement = document.getElementById("container");
const root = rootElement ? createRoot(rootElement) : undefined;

const Root = ({ title }) => {
  const [showSplash, setShowSplash] = React.useState(true);

  if (showSplash) {
    return <SplashScreen onComplete={() => setShowSplash(false)} />;
  }

  return <App title={title} />;
};

/* Render application after Office initializes */
Office.onReady(() => {
  applyAdminTheme();
  root?.render(
    <FluentProvider theme={adminFluentTheme}>
      <AuthProvider>
        <Root title={title} />
      </AuthProvider>
    </FluentProvider>
  );
});

// if (module.hot) {
//   module.hot.accept("./components/App", () => {
//     const NextApp = require("./components/App").default;
//     applyAdminTheme();
//     root?.render(
//       <FluentProvider theme={adminFluentTheme}>
//         <AuthProvider>
//           <NextApp title={title} />
//         </AuthProvider>
//       </FluentProvider>
//     );
//   });
// }
