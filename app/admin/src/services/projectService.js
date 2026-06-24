import { apiRequest } from '../msalConfig';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

// Determine API path based on environment
const API_PATH = API_BASE_URL.includes('localhost') || API_BASE_URL.includes('magic-brewing') ? 'api/admin/' : '';
const API_ADDINS_PATH = API_BASE_URL.includes('localhost') || API_BASE_URL.includes('magic-brewing') ? 'api/addins/' : '';

// API Endpoints
const API_ENDPOINTS = {
  CREATE_PROJECT: `${API_BASE_URL}${API_PATH}project/create-project`,
  LIST_PROJECTS: `${API_BASE_URL}${API_PATH}project/list`,
  PROJECT_COUNT: `${API_BASE_URL}${API_PATH}project-count`,
  EDIT_PROJECT: (projectId) => `${API_BASE_URL}${API_PATH}project/${projectId}/edit`,
  PROJECT_USERS: (projectId) => `${API_BASE_URL}${API_PATH}project/${projectId}/users`,
  ASSIGN_USER: (projectId) => `${API_BASE_URL}${API_PATH}project/${projectId}/assign-user`,
  DEACTIVATE_PROJECT: (projectId) => `${API_BASE_URL}${API_PATH}project/${projectId}/deactivate-project`,
  EDIT_USER_PERMISSION: (projectId, userId) => `${API_BASE_URL}${API_PATH}project/${projectId}/${userId}/edit-user`,
  UPLOAD_TEMPLATE: (projectId) => `${API_BASE_URL}${API_PATH}project/${projectId}/upload-template`,
  DOWNLOAD_TEMPLATE: (projectId) => `${API_BASE_URL}${API_ADDINS_PATH}project/${projectId}/download-base-file/`,
  
  // Asset Management endpoints
  LIST_ASSETS: (projectId) => `${API_BASE_URL}${API_PATH}project/${projectId}/assets/`,
  CREATE_ASSET: (projectId) => `${API_BASE_URL}${API_PATH}project/${projectId}/create-asset/`,
  GET_ASSET: (projectId, assetId) => `${API_BASE_URL}${API_PATH}project/${projectId}/edit-asset/${assetId}/`,
  UPDATE_ASSET: (projectId, assetId) => `${API_BASE_URL}${API_PATH}project/${projectId}/edit-asset/${assetId}/`,
  DELETE_ASSET: (projectId, assetId) => `${API_BASE_URL}${API_PATH}project/${projectId}/assets/${assetId}/`,
  TOGGLE_ASSET_STATUS: (projectId, assetId) => `${API_BASE_URL}${API_PATH}project/${projectId}/assets/${assetId}/toggle-status/`,
  UPLOAD_ASSET_BASE_FILE: (projectId, assetId) => `${API_BASE_URL}${API_PATH}project/${projectId}/assets/${assetId}/upload-asset-base-file/`,
};

export const projectService = {
  async createProject(msalInstance, account, projectData) {
    try {
      // Get access token from MSAL
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.CREATE_PROJECT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${tokenResponse.accessToken}`
        },
        body: JSON.stringify(projectData)
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error creating project:', error);
      throw error;
    }
  },

  async getAllProjects(msalInstance, account) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.LIST_PROJECTS, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error fetching projects:', error);
      throw error;
    }
  },

  async getProjectCount(msalInstance, account) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.PROJECT_COUNT, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error fetching project count:', error);
      throw error;
    }
  },

  async updateProject(msalInstance, account, projectId, projectData) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.EDIT_PROJECT(projectId), {
        method: 'PATCH',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(projectData)
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error updating project:', error);
      throw error;
    }
  },

  async getProjectUsers(msalInstance, account, projectId) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.PROJECT_USERS(projectId), {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error fetching project users:', error);
      throw error;
    }
  },

  async assignUserToProject(msalInstance, account, projectId, userData) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.ASSIGN_USER(projectId), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(userData)
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error assigning user to project:', error);
      throw error;
    }
  },

  async deactivateProject(msalInstance, account, projectId) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.DEACTIVATE_PROJECT(projectId), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ is_deleted: true })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error deactivating project:', error);
      throw error;
    }
  },

  async activateProject(msalInstance, account, projectId) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.DEACTIVATE_PROJECT(projectId), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ is_deleted: false })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error activating project:', error);
      throw error;
    }
  },

  async updateUserPermission(msalInstance, account, projectId, userId, permissionData) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.EDIT_USER_PERMISSION(projectId, userId), {
        method: 'PATCH',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(permissionData)
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error updating user permission:', error);
      throw error;
    }
  },

  async uploadTemplate(msalInstance, account, projectId, file) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const formData = new FormData();
      formData.append('template_file', file);

      const response = await fetch(API_ENDPOINTS.UPLOAD_TEMPLATE(projectId), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
        },
        body: formData
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error uploading template:', error);
      throw error;
    }
  },

  async getTemplateDownloadUrl(msalInstance, account, projectId) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const url = `${API_ENDPOINTS.DOWNLOAD_TEMPLATE(projectId)}`;

      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        }
        ,
        body: JSON.stringify({})
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      const result = await response.json();
      
      // Decode base64 and create a downloadable blob
      const byteCharacters = atob(result.file_base64);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], { type: result.content_type || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      
      // Create a download URL
      const downloadUrl = window.URL.createObjectURL(blob);
      
      return {
        url: downloadUrl,
        filename: result.filename || 'template.xlsx'
      };
    } catch (error) {
      console.error('Error getting template download URL:', error);
      throw error;
    }
  },

  async getAssetBaseFileDownloadUrl(msalInstance, account, projectId, assetId) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const url = `${API_ENDPOINTS.DOWNLOAD_TEMPLATE(projectId)}`;

      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        }
        ,
        body: JSON.stringify({ asset_id: assetId })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      const result = await response.json();

      const byteCharacters = atob(result.file_base64);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], { type: result.content_type || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      const filename = result.filename || 'asset-base-file.xlsx';

      const downloadUrl = window.URL.createObjectURL(blob);

      return {
        url: downloadUrl,
        filename
      };
    } catch (error) {
      console.error('Error getting asset base file download URL:', error);
      throw error;
    }
  },

  // ================ Asset Management Methods ================

  async getProjectAssets(msalInstance, account, projectId) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const url = `${API_ENDPOINTS.LIST_ASSETS(projectId)}`;
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error fetching project assets:', error);
      throw error;
    }
  },

  async createAsset(msalInstance, account, projectId, assetData) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.CREATE_ASSET(projectId), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(assetData)
      });

      if (!response.ok) {
        let errorMessage = `HTTP error! status: ${response.status}`;
        try {
          const errorData = await response.json();
          // Check for field-specific validation errors
          if (errorData.asset_unique_identifier) {
            errorMessage = errorData.asset_unique_identifier[0];
          } else if (errorData.detail) {
            errorMessage = errorData.detail;
          } else if (errorData.error) {
            errorMessage = errorData.error;
          } else {
            errorMessage = JSON.stringify(errorData);
          }
        } catch (e) {
          // If JSON parsing fails, try to get text
          const errorText = await response.text();
          if (errorText) errorMessage = errorText;
        }
        throw new Error(errorMessage);
      }

      return await response.json();
    } catch (error) {
      console.error('Error creating asset:', error);
      throw error;
    }
  },

  async updateAsset(msalInstance, account, projectId, assetId, assetData) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.UPDATE_ASSET(projectId, assetId), {
        method: 'PATCH',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(assetData)
      });

      if (!response.ok) {
        let errorMessage = `HTTP error! status: ${response.status}`;
        try {
          const errorData = await response.json();
          // Check for field-specific validation errors
          if (errorData.asset_unique_identifier) {
            errorMessage = errorData.asset_unique_identifier[0];
          } else if (errorData.detail) {
            errorMessage = errorData.detail;
          } else if (errorData.error) {
            errorMessage = errorData.error;
          } else {
            errorMessage = JSON.stringify(errorData);
          }
        } catch (e) {
          // If JSON parsing fails, try to get text
          const errorText = await response.text();
          if (errorText) errorMessage = errorText;
        }
        throw new Error(errorMessage);
      }

      return await response.json();
    } catch (error) {
      console.error('Error updating asset:', error);
      throw error;
    }
  },

  async deleteAsset(msalInstance, account, projectId, assetId) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.DELETE_ASSET(projectId, assetId), {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error deleting asset:', error);
      throw error;
    }
  },

  async toggleAssetStatus(msalInstance, account, projectId, assetId, isDeleted = true) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const response = await fetch(API_ENDPOINTS.TOGGLE_ASSET_STATUS(projectId, assetId), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ is_deleted: isDeleted })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error toggling asset status:', error);
      throw error;
    }
  },

  async uploadAssetBaseFile(msalInstance, account, projectId, assetId, file) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account
      });

      const formData = new FormData();
      formData.append('asset_file', file);

      const response = await fetch(API_ENDPOINTS.UPLOAD_ASSET_BASE_FILE(projectId, assetId), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${tokenResponse.accessToken}`,
        },
        body: formData
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error uploading asset base file:', error);
      throw error;
    }
  }
};
