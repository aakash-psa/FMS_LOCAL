import API_BASE_URL, { API_ENDPOINTS } from './apiConfig';

class ApiService {
  constructor() {
    this.baseUrl = API_BASE_URL;
    this.tokenProvider = null;
  }

  setTokenProvider(provider) {
    this.tokenProvider = provider;
  }

  async request(endpoint, options = {}) {
    try {
      if (!this.tokenProvider) {
        throw new Error('Token provider not configured');
      }

      const token = await this.tokenProvider();
      const url = `${this.baseUrl}${endpoint}`;

      const response = await fetch(url, {
        method: options.method || 'GET',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
          ...options.headers,
        },
        ...options,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('API call failed:', error);
      throw error;
    }
  }

  // Convenience methods
  async get(endpoint, options = {}) {
    return this.request(endpoint, { ...options, method: 'GET' });
  }

  async post(endpoint, data, options = {}) {
    return this.request(endpoint, {
      ...options,
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async put(endpoint, data, options = {}) {
    return this.request(endpoint, {
      ...options,
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async delete(endpoint, options = {}) {
    return this.request(endpoint, { ...options, method: 'DELETE' });
  }

  async patch(endpoint, data, options = {}) {
    return this.request(endpoint, {
      ...options,
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  // Project & Asset APIs
  async fetchUserProjects(userId) {
    return this.get(API_ENDPOINTS.USER_PROJECTS(userId));
  }

  async fetchProjectAssets(projectId) {
    return this.get(API_ENDPOINTS.PROJECT_ASSETS(projectId));
  }

  async fetchAssetDetail(projectId, assetId) {
    return this.get(API_ENDPOINTS.ASSET_DETAIL(projectId, assetId));
  }

  // Unified Scenario APIs (POST method)
  async fetchProjectScenarios(projectId, userIdOrPayload) {
    let payload = {};
    if (typeof userIdOrPayload === 'string' && userIdOrPayload) {
      payload = { user_id: userIdOrPayload };
    } else if (userIdOrPayload && typeof userIdOrPayload === 'object') {
      payload = userIdOrPayload;
    }
    return this.post(API_ENDPOINTS.SCENARIOS_UNIFIED(projectId), payload);
  }

  async loadScenario(projectId, scenarioId) {
    return this.post(API_ENDPOINTS.SCENARIOS_UNIFIED(projectId), { scenario_id: scenarioId });
  }

  // Asset Scenario APIs (AssetCo) - Now using unified API
  async fetchAssetScenarios(projectId, assetId) {
    return this.post(API_ENDPOINTS.ASSET_SCENARIOS(projectId, assetId), { asset_id: assetId });
  }

  async loadAssetScenario(projectId, assetId, scenarioId) {
    return this.post(API_ENDPOINTS.ASSET_SCENARIO_LOAD(projectId, assetId, scenarioId), {
      asset_id: assetId,
      scenario_id: scenarioId
    });
  }

  // Calculation APIs
  async calculateLandCo(inputData) {
    return this.post(API_ENDPOINTS.LANDCO_OUTPUT, inputData);
  }

  async calculateDevCo(inputData) {
    return this.post(API_ENDPOINTS.DEVCO_OUTPUT, inputData);
  }

  async calculateAssetCo(inputData, options = null) {
    if (options && typeof options === "object") {
      return this.post(API_ENDPOINTS.ASSETCO_OUTPUT, {
        input_json: inputData,
        ...options,
      });
    }
    return this.post(API_ENDPOINTS.ASSETCO_OUTPUT, inputData);
  }

  async calculateConsolidated(inputData) {
    return this.post(API_ENDPOINTS.CONSOLIDATED_OUTPUT, inputData);
  }

  // Save Iteration APIs
  async saveLandCoIteration(data) {
    return this.post(API_ENDPOINTS.LANDCO_SAVE, data);
  }

  async saveAssetCoIteration(data) {
    return this.post(API_ENDPOINTS.ASSETCO_SAVE, data);
  }

  async saveAssetCoConsolidatedIteration(data) {
    return this.post(API_ENDPOINTS.ASSETCO_CONSOLIDATED_SAVE, data);
  }

  async saveConsolidationIteration(data) {
    return this.post(API_ENDPOINTS.CONSOLIDATION_SAVE, data);
  }

  // Unified Save & Share APIs
  async saveIteration(data) {
    return this.post(API_ENDPOINTS.UNIFIED_SAVE_ITERATION, data);
  }

  async shareIteration(data) {
    // Unified share API using POST with parameters
    // Shared scenarios are read-only
    // Expected data: { iteration_id, target_user_id }
    return this.post(API_ENDPOINTS.SHARE_ITERATION, data);
  }

  // Template Download APIs
  async downloadTemplate(projectId) {
    return this.post(API_ENDPOINTS.DOWNLOAD_BASE_FILE(projectId), {});
  }

  async downloadLandCoDevCoTemplate(projectId) {
    return this.post(API_ENDPOINTS.DOWNLOAD_BASE_FILE(projectId), {});
  }

  async downloadAssetBaseFile(projectId, assetId) {
    return this.post(API_ENDPOINTS.DOWNLOAD_BASE_FILE(projectId), {
      asset_id: assetId,
    });
  }

  async fetchUsersDetails() {
    return this.get(API_ENDPOINTS.USERS_DETAILS);
  }

  // Asset Consolidation APIs
  async fetchJvScenarios(projectId) {
    return this.post(API_ENDPOINTS.JV_SCENARIOS, { project_id: projectId });
  }

  async fetchProjectConsolidationScenarios(projectId, input_json) {
    return this.post(API_ENDPOINTS.PROJECT_CONSOLIDATION_SCENARIOS, { project_id: projectId, input_json: input_json });
  }

  async fetchAllAssetScenarios(projectId) {
    return this.post(API_ENDPOINTS.ALL_ASSET_SCENARIOS, { project_id: projectId });
  }

  async normaliseData(data, normalizationType = 'default') {
    // data: JSON to normalize
    // normalizationType: 'default' | 'flatten' | 'consolidation'
    return this.post(API_ENDPOINTS.NORMALISATION, {
      data,
      normalization_type: normalizationType
    });
  }

  async normaliseIteration(iterationId) {
    const url = `${this.baseUrl}${API_ENDPOINTS.NORMALISATION}`;
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ iteration_id: iterationId }),
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }
    return response.json();
  }
}

export const apiService = new ApiService();
export { API_ENDPOINTS };
