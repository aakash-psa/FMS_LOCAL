import { useMsal, useIsAuthenticated } from "@azure/msal-react";
import { loginRequest } from "../msalConfig";

const LoginComponent = () => {
  const { instance } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  const handleLogin = () => {
    instance.loginPopup(loginRequest).catch((e) => {
      console.error(e);
    });
  };

  const handleLogout = () => {
    instance.logoutPopup().catch((e) => {
      console.error(e);
    });
  };

  if (!isAuthenticated) {
    return (
      <div style={{ margin: "20px" }}>
        <button
          onClick={handleLogin}
          style={{
            padding: "12px 24px",
            fontSize: "16px",
            backgroundColor: "#007bff",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
          }}
        >
          Sign In
        </button>
      </div>
    );
  }

  return (
    <div style={{ margin: "20px" }}>
      <button
        onClick={handleLogout}
        style={{
          padding: "8px 16px",
          backgroundColor: "#dc3545",
          color: "white",
          border: "none",
          borderRadius: "4px",
          cursor: "pointer",
        }}
      >
        Sign Out
      </button>
    </div>
  );
};

export default LoginComponent;
