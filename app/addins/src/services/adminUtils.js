export const openAdminPanel = () => {
  let adminUrl;

  const targetEnv = process.env.REACT_TARGET_ENV;

  if (targetEnv === "dev") {
    adminUrl = "https://dev-fms.roshn.sa/admin/";
  } else if (targetEnv === "uat") {
    adminUrl = "https://uat-fms.roshn.sa/admin/";
  } else if (targetEnv === "prod") {
    adminUrl = "https://fms.roshn.sa/admin/";
  } else {
    // Default to localhost for local development
    adminUrl = "http://localhost:5173/admin/";
  }

  window.open(adminUrl, "_blank", "noopener,noreferrer");
};
