/**
 * Auth0 Post-Login Action — mingai JIT Provisioning (P3AUTH-008) +
 * Group-to-Role Sync (P3AUTH-009)
 *
 * This action calls the mingai backend to:
 *   1. Provision users on first login (JIT provisioning).
 *   2. Sync IdP group claims to mingai roles (group sync).
 *
 * Deploy this to: Auth0 Dashboard > Actions > Flows > Login > Add Action
 *
 * Required secrets (set in Auth0 Action Secrets):
 *   BACKEND_URL        — e.g. https://api.mingai.app (no trailing slash)
 *   INTERNAL_SECRET_KEY — must match the value in backend .env
 *
 * Both calls are non-blocking: a failure logs an error but does NOT prevent
 * the user from completing login.
 */
const axios = require("axios");

exports.onExecutePostLogin = async (event, api) => {
  const backendUrl = event.secrets.BACKEND_URL || "http://localhost:8022";
  const internalSecret = event.secrets.INTERNAL_SECRET_KEY;

  // Step 1: JIT provisioning — creates user on first login, updates last_login_at otherwise.
  try {
    await axios.post(
      `${backendUrl}/internal/users/jit-provision`,
      {
        auth0_user_id: event.user.user_id,
        email: event.user.email,
        name: event.user.name || null,
        // Use Auth0 organization ID as the tenant identifier when available.
        // Falls back to "default" for connections outside an organization.
        tenant_id: event.organization?.id || "default",
        // Merge app_metadata groups + authorization roles into a single list.
        groups: [
          ...(event.user.app_metadata?.groups || []),
          ...(event.authorization?.roles || []),
        ],
      },
      {
        headers: { "X-Internal-Secret": internalSecret },
        timeout: 5000,
      },
    );
  } catch (err) {
    // Log but do not block login — JIT failure is non-fatal.
    console.log(`JIT provision failed: ${err.message}`);
  }

  // Step 2: Group sync — runs after JIT provisioning to map IdP groups to roles.
  // Failure is non-fatal and does not block login.
  await axios
    .post(
      `${backendUrl}/internal/users/sync-roles`,
      {
        auth0_user_id: event.user.user_id,
        groups:
          event.user.app_metadata?.groups || event.authorization?.roles || [],
        tenant_id: event.organization?.id || "default",
      },
      {
        headers: { "X-Internal-Secret": internalSecret },
        timeout: 5000,
      },
    )
    .catch((err) => console.log(`Group sync failed: ${err.message}`));
};
