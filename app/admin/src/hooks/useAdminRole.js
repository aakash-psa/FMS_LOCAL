import { useState, useEffect } from 'react';
import { useMsal } from '@azure/msal-react';

export const useAdminRole = () => {
  const { accounts } = useMsal();
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const checkAdminRole = () => {
      if (accounts.length > 0) {
        try {
          // Check for roles in the token claims
          const tokenClaims = accounts[0].idTokenClaims;
            const roles = tokenClaims?.roles || [];
          
          // Check if user has admin role
          const hasAdminClaim = roles.some(
            (role) => role.toLowerCase() === "admin"
          );

          setIsAdmin(hasAdminClaim);
        } catch (error) {
          console.error("Error checking admin role:", error);
          setIsAdmin(false);
        }
      } else {
        setIsAdmin(false);
      }
      setLoading(false);
    };

    checkAdminRole();
  }, [accounts]);

  return { isAdmin, loading };
};
