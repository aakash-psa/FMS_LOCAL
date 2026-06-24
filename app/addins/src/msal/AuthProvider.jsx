import React, { createContext, useContext, useEffect, useState } from "react";
import { PublicClientApplication } from "@azure/msal-browser";
import { msalConfig, loginRequest, apiRequest } from "./authConfig";
import { apiService, API_ENDPOINTS } from "../services/apiService";

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};

const msalInstance = new PublicClientApplication(msalConfig);

export const AuthProvider = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const initializeMsal = async () => {
      await msalInstance.initialize();
      
      // Configure API service with token provider
      apiService.setTokenProvider(async () => {
        return await acquireTokenSilent(apiRequest.scopes);
      });
      
      const accounts = msalInstance.getAllAccounts();
      if (accounts.length > 0) {
        setIsAuthenticated(true);
        setUser(accounts[0]);
      }
      setLoading(false);
    };

    initializeMsal();
  }, []);

  const signIn = async () => {
    try {
      const response = await msalInstance.loginPopup(loginRequest);
      setIsAuthenticated(true);
      setUser(response.account);

      // Log user assigned roles and token
      const idTokenClaims = response.idTokenClaims || {};

      return response;
    } catch (error) {
      console.error("Sign in failed:", error);
      throw error;
    }
  };

  const signOut = async () => {
    try {
      await msalInstance.logoutPopup({
        postLogoutRedirectUri: process.env.REACT_APP_MSAL_POST_LOGOUT_REDIRECT_URI,
        mainWindowRedirectUri: process.env.REACT_APP_MSAL_REDIRECT_URI
      });
      setIsAuthenticated(false);
      setUser(null);
      
      // Clear session storage
      sessionStorage.clear();
    } catch (error) {
      console.error("Sign out failed:", error);
      // Even if logout popup fails, reset local state
      setIsAuthenticated(false);
      setUser(null);
      sessionStorage.clear();
      throw error;
    }
  };

  const acquireTokenSilent = async (scopes = loginRequest.scopes) => {
    try {
      const accounts = msalInstance.getAllAccounts();
      if (accounts.length === 0) {
        throw new Error("No accounts found. Please sign in first.");
      }

      const request = {
        scopes,
        account: accounts[0],
        forceRefresh: false,
      };

      const response = await msalInstance.acquireTokenSilent(request);
      return response.accessToken;
    } catch (error) {
      console.error("Silent token acquisition failed:", error);

      // If silent token acquisition fails, try interactive method
      if (error.name === "InteractionRequiredAuthError") {
        try {
          const response = await msalInstance.acquireTokenPopup({ scopes });
          return response.accessToken;
        } catch (interactiveError) {
          console.error("Interactive token acquisition failed:", interactiveError);
          throw interactiveError;
        }
      }
      throw error;
    }
  };

  // const callGraphAPI = async (endpoint, options = {}) => {
  //   try {
  //     const token = await acquireTokenSilent();
  //     const response = await fetch(`https://graph.microsoft.com/v1.0${endpoint}`, {
  //       headers: {
  //         Authorization: `Bearer ${token}`,
  //         "Content-Type": "application/json",
  //         ...options.headers,
  //       },
  //       ...options,
  //     });

  //     if (!response.ok) {
  //       throw new Error(`HTTP error! status: ${response.status}`);
  //     }

  //     return await response.json();
  //   } catch (error) {
  //     console.error("Graph API call failed:", error);
  //     throw error;
  //   }
  // };

  const callBackendAPI = async (endpoint, options = {}) => {
    try {
      return await apiService.request(endpoint, options);
    } catch (error) {
      console.error("Backend API call failed:", error);
      throw error;
    }
  };

  const getUserProjects = async () => {
    try {
      const accounts = msalInstance.getAllAccounts();
      const userId = accounts[0]?.localAccountId;
      const endpoint = API_ENDPOINTS.USER_PROJECTS(userId);
      return await apiService.get(endpoint);
    } catch (error) {
      console.error("Failed to fetch user projects:", error);
      throw error;
    }
  };

  const getProjectScenarios = async (projectId) => {
    try {
      const accounts = msalInstance.getAllAccounts();
      // const userId = accounts[0]?.localAccountId;
      const endpoint = API_ENDPOINTS.PROJECT_SCENARIOS(projectId);
      return await apiService.get(endpoint);
    } catch (error) {
      console.error("Failed to fetch project scenarios:", error);
      throw error;
    }
  };

  const loadScenarioData = async (projectId, scenarioId) => {
    try {
      const endpoint = API_ENDPOINTS.SCENARIO_LOAD(projectId, scenarioId);
      return await apiService.get(endpoint);
    } catch (error) {
      console.error("Failed to load scenario data:", error);
      throw error;
    }
  };

  const saveScenario = async (projectId, scenarioName, inputJson) => {
    try {
      const endpoint = API_ENDPOINTS.LANDCO_SAVE;
      const payload = {
        project_id: projectId,
        name: scenarioName,
        input_json: inputJson
      };
      return await apiService.post(endpoint, payload);
    } catch (error) {
      console.error("Failed to save scenario:", error);
      throw error;
    }
  };

  const downloadTemplate = async (projectId) => {
    try {
      // Return the API response (expected JSON with base64 file data)
      return await apiService.downloadTemplate(projectId);
    } catch (error) {
      console.error("Failed to download template:", error);
      throw error;
    }
  };

  const value = {
    isAuthenticated,
    user,
    signIn,
    signOut,
    loading,
    msalInstance,
    acquireTokenSilent,
    // callGraphAPI,
    callBackendAPI,
    getUserProjects,
    getProjectScenarios,
    loadScenarioData,
    saveScenario,
    downloadTemplate,
    apiService, // Expose apiService for direct use
    API_ENDPOINTS, // Expose endpoints for reference
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
