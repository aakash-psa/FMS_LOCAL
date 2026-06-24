import { useAccount, useMsal } from "@azure/msal-react";

const ProfileComponent = () => {
  const { accounts } = useMsal();
  const account = useAccount(accounts[0] || {});

  if (account) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "flex-start",
        }}
      >
        <p>Welcome, {account.name}</p>
        {/* <p style={{ marginLeft: "20px" }}>Username: {account.username}</p> */}
        {/* <p>Account ID: {account.localAccountId}</p> */}
      </div>
    );
  } else {
    return <p>Please sign in to view your profile.</p>;
  }
};

export default ProfileComponent;
