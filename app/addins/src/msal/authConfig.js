import { LogLevel } from '@azure/msal-browser';

 /**
 * Configuration object to be passed to MSAL instance on creation. 
 * For a full list of MSAL.js configuration parameters, visit:
 * https://github.com/AzureAD/microsoft-authentication-library-for-js/blob/dev/lib/msal-browser/docs/configuration.md 
 */

 export const msalConfig = {
     auth: {
         clientId: process.env.REACT_APP_MSAL_CLIENT_ID, // from .env
         authority: process.env.REACT_APP_MSAL_AUTHORITY, // from .env
         redirectUri: process.env.REACT_APP_MSAL_REDIRECT_URI, // from .env
         postLogoutRedirectUri: process.env.REACT_APP_MSAL_POST_LOGOUT_REDIRECT_URI || '/', // from .env or default
         navigateToLoginRequestUrl: false, // If "true", will navigate back to the original request location before processing the auth code response.
     },
     cache: {
         cacheLocation: 'sessionStorage', // Configures cache location. "sessionStorage" is more secure, but "localStorage" gives you SSO between tabs.
         storeAuthStateInCookie: false, // Set this to "true" if you are having issues on IE11 or Edge
     },
     system: {
         loggerOptions: {
             loggerCallback: (level, message, containsPii) => {
                 if (containsPii) {
                     return;
                 }
                 switch (level) {
                     case LogLevel.Error:
                         console.error(message);
                         return;
                     case LogLevel.Info:
                         console.info(message);
                         return;
                     case LogLevel.Verbose:
                         console.debug(message);
                         return;
                     case LogLevel.Warning:
                         console.warn(message);
                         return;
                     default:
                         return;
                 }
             },
         },
     },
 };

 /**
 * Scopes you add here will be prompted for user consent during sign-in.
 * By default, MSAL.js will add OIDC scopes (openid, profile, email) to any login request.
 * For more information about OIDC scopes, visit: 
 * https://docs.microsoft.com/en-us/azure/active-directory/develop/v2-permissions-and-consent#openid-connect-scopes
 */
 export const loginRequest = {
     scopes: ["User.Read"],
 };

 export const apiRequest = {
  scopes: [`${process.env.REACT_APP_MSAL_CLIENT_ID}/.default`]
};