import { graphRequestAssigned, apiRequest, loginRequest } from "../msalConfig";

const GRAPH_BASE_URL = "https://graph.microsoft.com";
const GRAPH_ENDPOINT = `${GRAPH_BASE_URL}/users`;
const SERVICE_PRINCIPALS_ENDPOINT = `${GRAPH_BASE_URL}/servicePrincipals`;
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "https://localhost:8000/";

// Replace with your actual app client ID from Azure AD
const APP_CLIENT_ID = import.meta.env.VITE_MSAL_CLIENT_ID;
// Determine API path based on environment
const API_PATH =
  API_BASE_URL.includes("localhost") || API_BASE_URL.includes("magic-brewing")
    ? "api/admin/"
    : "";

// API Endpoints
const API_ENDPOINTS = {
  SYNC_USERS: `${API_BASE_URL}${API_PATH}users/sync`,
  USERS_DETAILS: `${API_BASE_URL}${API_PATH}users-details`,
  GRAPH_USERS: `${GRAPH_BASE_URL}/users`,
  GRAPH_SERVICE_PRINCIPALS: `${GRAPH_BASE_URL}/servicePrincipals`,
  GRAPH_V1: `${GRAPH_BASE_URL}/v1.0`,
};

export const userService = {
  
  validateGraphUrl(url) {
    if (!url.startsWith('https://graph.microsoft.com')) {
      throw new Error('Invalid Graph API URL: must use HTTPS and graph.microsoft.com domain');
    }
    return url;
  },

  async getServicePrincipalId(msalInstance, account) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...graphRequestAssigned,
        account: account,
      });

      const url = new URL(API_ENDPOINTS.GRAPH_SERVICE_PRINCIPALS);
      url.searchParams.set('$filter', `appId eq '${APP_CLIENT_ID}'`);

      const response = await fetch(url, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${tokenResponse.accessToken}`,
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(
          `Failed to get service principal: ${response.statusText}`
        );
      }

      const data = await response.json();
      if (data.value && data.value.length > 0) {
        return data.value[0].id;
      }
      throw new Error("Service principal not found");
    } catch (error) {
      console.error("Error fetching service principal:", error);
      throw error;
    }
  },

  async validateServicePrincipalId(spId) {
    const guidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!guidRegex.test(spId)) {
      throw new Error("Invalid service principal ID forsmat");
    }
    return spId;
  },

  async getAllUsers(msalInstance, account) {
  try {
    const tokenResponse = await msalInstance.acquireTokenSilent({
      scopes: ["User.Read","GroupMember.Read.All"],
      account: account
    });
    const headers = {
      Authorization: `Bearer ${tokenResponse.accessToken}`,
      "Content-Type": "application/json",
    };

    this.validateGraphUrl(API_ENDPOINTS.GRAPH_V1);
    const spUrl = new URL(`servicePrincipals`, `${API_ENDPOINTS.GRAPH_V1}/`);
    spUrl.searchParams.set('$filter', `appId eq '${APP_CLIENT_ID}'`);
    const spResp = await fetch(spUrl, { headers });
    const spData = await spResp.json();
    if (!spData.value || spData.value.length === 0) throw new Error("Service principal not found");
    const servicePrincipalId = spData.value[0].id;
    const safeSpId = await this.validateServicePrincipalId(servicePrincipalId);
    const assignmentsUrl = new URL(`servicePrincipals/${encodeURIComponent(safeSpId)}/appRoleAssignedTo`, `${API_ENDPOINTS.GRAPH_V1}/`);

    const assignmentsResp = await fetch(assignmentsUrl, { headers });
    const assignments = (await assignmentsResp.json()).value;

    const allUsers = [];
    const processedIds = new Set();

    // Direct users - use data from appRoleAssignedTo
    for (const user of assignments.filter(a => a.principalType === "User")) {
      if (processedIds.has(user.principalId)) continue;
      allUsers.push({
        id: user.principalId,
        displayName: user.principalDisplayName,
        userPrincipalName: user.principalDisplayName,
        mail: "",
        accountEnabled: true,
        givenName: user.principalDisplayName?.split(" ")[0] || "",
        surname: user.principalDisplayName?.split(" ").slice(1).join(" ") || "",
        appRoleId: user.appRoleId,
        fromGroup: null
      });
      processedIds.add(user.principalId);
    }

    // Users in groups - members endpoint returns full details
    for (const group of assignments.filter(a => a.principalType === "Group")) {
      const membersUrl = new URL(`groups/${group.principalId}/members`, `${API_ENDPOINTS.GRAPH_V1}/`);
      membersUrl.searchParams.set('$select', 'id,displayName,userPrincipalName,mail,accountEnabled,givenName,surname');
      let url = membersUrl.toString();
      while (url) {
        const resp = await fetch(url, { headers });
        if (!resp.ok) break;
        const data = await resp.json();
        for (const member of data.value) {
          if (member["@odata.type"] === "#microsoft.graph.user" && !processedIds.has(member.id)) {
            allUsers.push({
              id: member.id,
              displayName: member.displayName,
              userPrincipalName: member.userPrincipalName,
              mail: member.mail || member.userPrincipalName,
              accountEnabled: member.accountEnabled ?? true,
              givenName: member.givenName,
              surname: member.surname,
              appRoleId: group.appRoleId,
              fromGroup: group.principalDisplayName
            });
            processedIds.add(member.id);
          }
        }
        url = data["@odata.nextLink"] || null;
        // Validate nextLink is from Microsoft Graph API
        if (url) {
          try {
            this.validateGraphUrl(url);
          } catch (e) {
            console.warn(`Skipping invalid nextLink URL: ${url}`);
            url = null;
          }
        }
      }
    }
    return allUsers;

  } catch (err) {
    console.error("Error in getAllUsers:", err);
    throw err;
  }
  },

  // async getUserById(msalInstance, account, userId) {
  //   try {
  //     const tokenResponse = await msalInstance.acquireTokenSilent({
  //       ...graphRequestAssigned,
  //       account: account
  //     });

  //     const response = await fetch(`${GRAPH_ENDPOINT}/${userId}`, {
  //       method: 'GET',
  //       headers: {
  //         'Authorization': `Bearer ${tokenResponse.accessToken}`,
  //         'Content-Type': 'application/json'
  //       }
  //     });

  //     if (!response.ok) {
  //       throw new Error(`Graph API failed: ${response.statusText}`);
  //     }

  //     return await response.json();
  //   } catch (error) {
  //     console.error('Error fetching user by ID:', error);
  //     throw error;
  //   }
  // },

  async syncUsersToDatabase(msalInstance, account, users, groupId = "") {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account,
      });

      // Transform users to match the expected format
      const transformedUsers = users.map((user) => ({
        user_id: user.id,
        email: user.mail || user.userPrincipalName || "",
        first_name: user.givenName || user.displayName?.split(" ")[0] || "",
        last_name:
          user.surname || user.displayName?.split(" ").slice(1).join(" ") || "",
      }));

      const response = await fetch(API_ENDPOINTS.SYNC_USERS, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${tokenResponse.accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          users: transformedUsers,
          group_id: groupId,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Sync failed: ${response.status}, message: ${errorText}`
        );
      }

      return await response.json();
    } catch (error) {
      console.error("Error syncing users to database:", error);
      throw error;
    }
  },

  async getUsersWithPermissions(msalInstance, account) {
    try {
      const tokenResponse = await msalInstance.acquireTokenSilent({
        ...apiRequest,
        account: account,
      });

      const response = await fetch(API_ENDPOINTS.USERS_DETAILS, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${tokenResponse.accessToken}`,
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to fetch users: ${response.status}, message: ${errorText}`
        );
      }

      return await response.json();
    } catch (error) {
      console.error("Error fetching users with permissions:", error);
      throw error;
    }
  },
};
