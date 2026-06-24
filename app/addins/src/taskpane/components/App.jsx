import * as React from "react";
import { useState, useEffect } from "react";
import PropTypes from "prop-types";
import { MemoryRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import SignIn from "./SignIn";
import ProjectList from "./ProjectList";
import ModelSelection from "./ModelSelection";
import Scenarios from "./Scenarios";
import AssetCoScenarios from "./AssetCoScenarios";
import AssetScenarioDetail from "./AssetScenarioDetail";
import AssetCoConsolidated from "./AssetCoConsolidated";
import ROSHNConsolidated from "./ROSHNConsolidated";
import JVConsolidation from "./JVConsolidation";
import Consolidation from "./Consolidation";
import Header from "./Header";
import { makeStyles, Spinner } from "@fluentui/react-components";
import { useAuth } from "../../msal/AuthProvider";

const useStyles = makeStyles({
  root: {
    minHeight: "100vh",
    background: "var(--bg-primary)",
    color: "var(--text-primary)",
  },
  loading: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    minHeight: "100vh",
    background: "var(--bg-primary)",
  },
});

const App = (props) => {
  const { title } = props;
  const styles = useStyles();
  const { isAuthenticated, loading } = useAuth();
  const [isSignedIn, setIsSignedIn] = useState(false);

  useEffect(() => {
    if (isAuthenticated) {
      setIsSignedIn(true);
    } else {
      setIsSignedIn(false);
    }
  }, [isAuthenticated]);

  if (loading) {
    return (
      <div className={styles.loading}>
        <Spinner size="large" label="Loading..." />
      </div>
    );
  }

  if (!isSignedIn) {
    return <SignIn onSignIn={() => setIsSignedIn(true)} />;
  }

  return (
    <Router>
      <div >
        <Header />
        <Routes>
          <Route path="/" element={<ProjectList />} />
          <Route path="/model-selection" element={<ModelSelection />} />
          <Route path="/scenarios" element={<Scenarios />} />
          <Route path="/assetco" element={<AssetCoScenarios />} />
          <Route path="/assetco/:assetId" element={<AssetScenarioDetail />} />
          <Route path="/assetco-consolidated" element={<AssetCoConsolidated />} />
          <Route path="/roshn-consolidated" element={<ROSHNConsolidated />} />
          <Route path="/jv-consolidation" element={<JVConsolidation />} />
          <Route path="/consolidation" element={<Consolidation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </Router>
  );
};

App.propTypes = {
  title: PropTypes.string,
};

export default App;
