import React, { useState } from "react";
import { Button, Card, Spinner } from "@fluentui/react-components";
import { Shield24Regular } from "@fluentui/react-icons";
import { useAuth } from "../../msal/AuthProvider";
import { openAdminPanel } from "../../services/adminUtils";
import logo from "../../assets/c_logo.png";

const SignIn = ({ onSignIn }) => {
  const { signIn } = useAuth();
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [error, setError] = useState(null);

  const handleSignIn = async () => {
    setIsSigningIn(true);
    setError(null);

    try {
      await signIn();
      if (onSignIn) {
        onSignIn();
      }
    } catch (error) {
      setError("Sign in failed. Please try again.");
      console.error("Sign in error:", error);
    } finally {
      setIsSigningIn(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "100vh",
        padding: "16px",
        background: "var(--bg-primary)",
        boxSizing: "border-box",
      }}
    >
      <Card
        style={{
          padding: "24px",
          width: "100%",
          maxWidth: "280px",
          textAlign: "center",
          background: "var(--bg-secondary)",
          color: "var(--text-primary)",
          borderRadius: "8px",
          boxShadow: "var(--card-shadow)",
          border: "1px solid var(--border-color)",
        }}
      >
        <img
          src={logo}
          alt="FMS Logo"
          style={{
            width: "120px",
            height: "auto",
            marginBottom: "16px",
            display: "block",
            marginLeft: "auto",
            marginRight: "auto",
          }}
        />
        <h2
          style={{
            fontSize: "18px",
            fontWeight: "600",
            marginBottom: "8px",
            lineHeight: "1.4",
          }}
        >
          Welcome to FMS Add-ins
        </h2>
        <p
          style={{
            fontSize: "14px",
            marginBottom: "20px",
            lineHeight: "1.4",
            color: "var(--text-secondary)",
          }}
        >
          Please sign in with your Microsoft account to continue.
        </p>

        {error && (
          <div
            style={{
              color: "var(--error-text)",
              marginBottom: "16px",
              fontSize: "13px",
              padding: "8px",
              background: "var(--error-bg)",
              borderRadius: "4px",
              border: "1px solid var(--error-color)",
            }}
          >
            {error}
          </div>
        )}

        <Button
          appearance="primary"
          size="medium"
          onClick={handleSignIn}
          disabled={isSigningIn}
          style={{
            width: "100%",
            height: "40px",
            fontSize: "14px",
            fontWeight: "600",
          }}
        >
          {isSigningIn ? (
            <>
              <Spinner size="tiny" style={{ marginRight: "8px" }} />
              Signing in...
            </>
          ) : (
            "Sign in with Microsoft"
          )}
        </Button>

        <Button
          appearance="primary"
          size="medium"
          icon={<Shield24Regular />}
          onClick={openAdminPanel}
          style={{
            width: "100%",
            height: "40px",
            fontSize: "14px",
            fontWeight: "600",
          }}
        >
          Admin Panel
        </Button>
      </Card>
    </div>
  );
};

export default SignIn;
