// Auth modal flow and role-based UI controls for dashboard pages.
(function () {
  function createApi() {
    function applyRolePermissions() {
      const userRole = sessionStorage.getItem('userRole') || 'viewer';
      const downloadBtn = document.getElementById('downloadBtn');
      const managerBtn = document.querySelector('.manager-btn');
      const adminBtn = document.querySelector('.admin-btn');
      const loginUpgradeIcon = document.getElementById('loginUpgradeIcon');

      if (userRole === 'viewer') {
        if (downloadBtn) downloadBtn.style.display = 'none';
        if (managerBtn) managerBtn.style.display = 'none';
        if (adminBtn) adminBtn.style.display = 'none';
        if (loginUpgradeIcon) loginUpgradeIcon.style.display = 'inline-block';
      } else if (userRole === 'manager') {
        if (downloadBtn) downloadBtn.style.display = 'inline-block';
        if (managerBtn) managerBtn.style.display = 'inline-block';
        if (adminBtn) adminBtn.style.display = 'none';
        if (loginUpgradeIcon) loginUpgradeIcon.style.display = 'inline-block';
      } else if (userRole === 'admin') {
        if (downloadBtn) downloadBtn.style.display = 'inline-block';
        if (managerBtn) managerBtn.style.display = 'inline-block';
        if (adminBtn) adminBtn.style.display = 'inline-block';
        if (loginUpgradeIcon) loginUpgradeIcon.style.display = 'none';
      }
    }

    async function showLoginModal() {
      const modal = document.getElementById('loginModal');
      const form = document.getElementById('loginForm');
      const accessMsg = document.getElementById('accessMessage');
      const passwordInput = document.getElementById('passwordInput');
      const accessGranted = document.getElementById('accessGranted');

      if (!modal || !form || !accessMsg || !passwordInput || !accessGranted) {
        return;
      }

      modal.classList.remove('hidden');
      accessMsg.textContent = 'This dashboard is protected. External access requires a password.';
      form.style.display = 'flex';
      accessGranted.style.display = 'none';

      if (!form.dataset.bound) {
        form.dataset.bound = 'true';
        form.addEventListener('submit', async (e) => {
          e.preventDefault();
          const password = passwordInput.value;

          try {
            const loginRes = await fetch('/auth/login', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ password })
            });

            if (loginRes.ok) {
              const loginData = await loginRes.json();
              if (loginData.device_token) {
                localStorage.setItem('deviceToken', loginData.device_token);
              }
              if (loginData.role) {
                sessionStorage.setItem('userRole', loginData.role);
              }
              sessionStorage.setItem('authToken', loginData.token);

              if (window.DashboardAuth && window.DashboardAuth.setupAuthHeaders) {
                window.DashboardAuth.setupAuthHeaders(loginData.token);
              }

              applyRolePermissions();
              form.style.display = 'none';
              accessGranted.style.display = 'block';

              setTimeout(() => {
                modal.classList.add('hidden');
              }, 1000);
            } else {
              passwordInput.style.borderColor = '#f44336';
              passwordInput.value = '';
              accessMsg.textContent = 'Invalid password. Please try again.';
              accessMsg.style.color = '#f44336';
              setTimeout(() => {
                passwordInput.style.borderColor = 'var(--ring-secondary)';
                accessMsg.style.color = 'var(--muted)';
                accessMsg.textContent = 'This dashboard is protected. External access requires a password.';
              }, 2000);
            }
          } catch (err) {
            console.error('Login failed:', err);
            accessMsg.textContent = 'Connection error. Please try again.';
            accessMsg.style.color = '#f44336';
          }
        });
      }

      const dismissBtn = document.getElementById('dismissLoginBtn');
      if (dismissBtn && !dismissBtn.dataset.bound) {
        dismissBtn.dataset.bound = 'true';
        dismissBtn.addEventListener('click', async (e) => {
          e.preventDefault();
          sessionStorage.setItem('loginDismissed', '1');
          sessionStorage.setItem('userRole', 'viewer');
          applyRolePermissions();

          try {
            let deviceName = '';
            try {
              deviceName = (window.prompt && window.prompt('Name this device (optional):', '')) || '';
            } catch (_promptErr) {
              deviceName = '';
            }

            const res = await fetch('/auth/ephemeral-viewer', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name: deviceName })
            });
            if (res.ok) {
              const data = await res.json();
              if (data.device_token) {
                localStorage.setItem('deviceToken', data.device_token);
                sessionStorage.setItem('authToken', data.token || data.device_token);
                if (window.DashboardAuth && window.DashboardAuth.setupAuthHeaders) {
                  window.DashboardAuth.setupAuthHeaders(data.token || data.device_token);
                }
              }
            } else {
              sessionStorage.setItem('authToken', 'viewer-dismissed');
            }
          } catch (err) {
            console.warn('Ephemeral viewer token request failed:', err);
            sessionStorage.setItem('authToken', 'viewer-dismissed');
          }

          modal.classList.add('hidden');
        });
      }

      passwordInput.focus();
    }

    async function checkAuth() {
      try {
        const existingToken = (window.DashboardAuth && window.DashboardAuth.getExistingToken)
          ? window.DashboardAuth.getExistingToken()
          : (sessionStorage.getItem('authToken') || localStorage.getItem('deviceToken'));

        if (existingToken) {
          try {
            const statusRes = await fetch('/auth/status', {
              headers: { 'Authorization': 'Bearer ' + existingToken }
            });
            if (statusRes.ok) {
              const statusData = await statusRes.json();
              if (statusData.role) {
                sessionStorage.setItem('userRole', statusData.role);
              }
              if (statusData.authenticated) {
                if (window.DashboardAuth && window.DashboardAuth.setupAuthHeaders) {
                  window.DashboardAuth.setupAuthHeaders(existingToken);
                }
                return true;
              }
            }
          } catch (statusErr) {
            console.warn('Auth status with token failed:', statusErr);
          }
        }

        const authRes = await fetch('/auth/status');
        const authData = await authRes.json();

        if (authData.role) {
          sessionStorage.setItem('userRole', authData.role);
        }

        if (authData.authenticated) {
          if (authData.role === 'viewer') {
            sessionStorage.setItem('userRole', 'viewer');
          }
          return true;
        }

        if (sessionStorage.getItem('loginDismissed')) {
          sessionStorage.setItem('userRole', 'viewer');
          applyRolePermissions();
          return true;
        }

        await showLoginModal();
        return false;
      } catch (err) {
        console.error('Auth check failed:', err);
        if (sessionStorage.getItem('loginDismissed')) {
          sessionStorage.setItem('userRole', 'viewer');
          applyRolePermissions();
          return true;
        }
        await showLoginModal();
        return false;
      }
    }

    async function waitForAuthToken() {
      await new Promise((resolve) => {
        const checkInterval = setInterval(() => {
          const token = sessionStorage.getItem('authToken');
          if (token) {
            clearInterval(checkInterval);
            if (window.DashboardAuth && window.DashboardAuth.setupAuthHeaders) {
              window.DashboardAuth.setupAuthHeaders(token);
            }
            resolve();
          }
        }, 100);
      });
    }

    function bindUpgradeIcon() {
      const loginUpgradeIcon = document.getElementById('loginUpgradeIcon');
      if (loginUpgradeIcon && !loginUpgradeIcon.dataset.bound) {
        loginUpgradeIcon.dataset.bound = 'true';
        loginUpgradeIcon.addEventListener('click', () => {
          showLoginModal();
        });
      }
    }

    async function ensureAuthenticated() {
      const isAuthenticated = await checkAuth();
      if (!isAuthenticated) {
        await waitForAuthToken();
      }
      applyRolePermissions();
      bindUpgradeIcon();
    }

    return {
      applyRolePermissions,
      showLoginModal,
      checkAuth,
      waitForAuthToken,
      bindUpgradeIcon,
      ensureAuthenticated,
    };
  }

  window.DashboardAuthUI = {
    init() {
      return createApi();
    },
  };
})();
