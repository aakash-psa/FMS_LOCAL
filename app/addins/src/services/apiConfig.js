const API_BASE_URL = process.env.REACT_API_BASE_URL || 'http://localhost:8000/';

// API Endpoints Configuration
// Determine API path based on environment
const API_PATH =
  API_BASE_URL.includes('localhost') || API_BASE_URL.includes('magic-brewing')
    ? 'api/addins/'
    : '';

const ADMIN_API_PATH =
  API_BASE_URL.includes('localhost') || API_BASE_URL.includes('magic-brewing')
    ? 'api/admin/'
    : '';


export const API_ENDPOINTS = {
  // User & Projects
  USER_PROJECTS: (userId) => `${API_PATH}user/projects/?user_id=${userId}`,
  
  // Scenarios (LandCo/DevCo)
  PROJECT_SCENARIOS: (projectId) => `${API_PATH}project/${projectId}/scenarios/`,
  SCENARIO_LOAD: (projectId, scenarioId) => `${API_PATH}project/${projectId}/scenarios/${scenarioId}/`,
  
  // Unified Scenarios API (POST for filtering)
  SCENARIOS_UNIFIED: (projectId) => `${API_PATH}project/${projectId}/scenarios/`,
  
  // Asset Management
  PROJECT_ASSETS: (projectId) => `${ADMIN_API_PATH}project/${projectId}/assets/`,
  ASSET_DETAIL: (projectId, assetId) => `${ADMIN_API_PATH}project/${projectId}/edit-asset/${assetId}/`,
  
  // Asset-specific Scenarios (AssetCo iterations) - Now use unified API
  ASSET_SCENARIOS: (projectId, assetId) => `${API_PATH}project/${projectId}/scenarios/`,
  ASSET_SCENARIO_LOAD: (projectId, assetId, scenarioId) => `${API_PATH}project/${projectId}/scenarios/`,
  
  // Template Downloads
  DOWNLOAD_BASE_FILE: (projectId) => `${API_PATH}project/${projectId}/download-base-file/`,
  
  // Calculations
  LANDCO_OUTPUT: `${API_PATH}landco/output-json`,
  DEVCO_OUTPUT: `${API_PATH}devco/output-json`,
  ASSETCO_OUTPUT: `${API_PATH}assetco/output-json`,
  CONSOLIDATED_OUTPUT: `${API_PATH}consolidated/output-json`,
  
  // Save Iterations
  LANDCO_SAVE: `${API_PATH}landco/save-iteration`,
  ASSETCO_SAVE: `${API_PATH}assetco/save-iteration`,
  ASSETCO_CONSOLIDATED_SAVE: `${API_PATH}assetco-consolidated/save-iteration`,
  CONSOLIDATION_SAVE: `${API_PATH}consolidation/save-iteration`,
  
  // Unified Save & Share
  UNIFIED_SAVE_ITERATION: `${API_PATH}iteration/save/`,
  SHARE_ITERATION: `${API_PATH}iteration/share/`,  // POST with {iteration_id, target_user_id} - read-only access
  USERS_DETAILS: `${ADMIN_API_PATH}users-details`,
  
  // Asset Consolidation
  JV_SCENARIOS: `${API_PATH}jv-scenarios/`,
  PROJECT_CONSOLIDATION_SCENARIOS: `${API_PATH}project-consolidation-scenarios/`,
  ALL_ASSET_SCENARIOS: `${API_PATH}asset-scenarios/`,  // POST with { project_id }

  // Normalisation
  NORMALISATION: `${ADMIN_API_PATH}normalisation/`,  // POST with { iteration_id }
};

export default API_BASE_URL;
