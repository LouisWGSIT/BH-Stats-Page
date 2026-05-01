// Auth modal flow and role-based UI controls for dashboard pages.
(function () {
  function createApi() {
    let loginContext = {
      viewerPasswordRequired: false,
      isTvBrowser: false,
    };

    function createTvKeypad(passwordInput, submitButton) {
      const keypad = document.getElementById('tvKeypad');
      const clearPasswordBtn = document.getElementById('clearPasswordBtn');
      if (!keypad || !passwordInput) {
        return;
      }

      keypad.innerHTML = '';

      const rows = [
        ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
        ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
        ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L'],
        ['Z', 'X', 'C', 'V', 'B', 'N', 'M'],
      ];
      const letterKeys = [];
      let lowercaseMode = false;

      function appendValue(value) {
        passwordInput.value = (passwordInput.value || '') + value;
        passwordInput.focus();
      }

      rows.forEach((rowValues) => {
        const rowEl = document.createElement('div');
        rowEl.className = 'tv-keypad-row';

        rowValues.forEach((value) => {
          const key = document.createElement('button');
          key.type = 'button';
          key.className = 'tv-key';
          key.textContent = value;
          key.dataset.kind = /^[A-Z]$/.test(value) ? 'letter' : 'digit';
          key.dataset.base = value;
          key.addEventListener('click', () => {
            const keyValue = key.dataset.value || key.textContent;
            appendValue(keyValue);
          });
          if (key.dataset.kind === 'letter') {
            letterKeys.push(key);
          }
          rowEl.appendChild(key);
        });

        keypad.appendChild(rowEl);
      });

      const controlsEl = document.createElement('div');
      controlsEl.className = 'tv-keypad-row tv-keypad-controls';

      const lowercaseKey = document.createElement('button');
      lowercaseKey.type = 'button';
      lowercaseKey.className = 'tv-key tv-key-action';
      lowercaseKey.textContent = 'a-z';
      lowercaseKey.addEventListener('click', () => {
        lowercaseMode = !lowercaseMode;
        lowercaseKey.textContent = lowercaseMode ? 'A-Z' : 'a-z';
        letterKeys.forEach((letterKey) => {
          const base = (letterKey.dataset.base || '').toUpperCase();
          const next = lowercaseMode ? base.toLowerCase() : base;
          letterKey.textContent = next;
          letterKey.dataset.value = next;
        });
      });

      const symbolKey = document.createElement('button');
      symbolKey.type = 'button';
      symbolKey.className = 'tv-key tv-key-action';
      symbolKey.textContent = 'Symbol';
      symbolKey.addEventListener('click', () => {
        appendValue('-');
      });

      const backspaceKey = document.createElement('button');
      backspaceKey.type = 'button';
      backspaceKey.className = 'tv-key tv-key-action';
      backspaceKey.textContent = 'Backspace';
      backspaceKey.addEventListener('click', () => {
        passwordInput.value = (passwordInput.value || '').slice(0, -1);
        passwordInput.focus();
      });

      controlsEl.appendChild(lowercaseKey);
      controlsEl.appendChild(symbolKey);
      controlsEl.appendChild(backspaceKey);
      keypad.appendChild(controlsEl);

      if (clearPasswordBtn && !clearPasswordBtn.dataset.bound) {
        clearPasswordBtn.dataset.bound = 'true';
        clearPasswordBtn.addEventListener('click', () => {
          passwordInput.value = '';
          passwordInput.focus();
        });
      }

      if (submitButton) {
        const submitRow = document.createElement('div');
        submitRow.className = 'tv-keypad-row';
        const submitClone = document.createElement('button');
        submitClone.type = 'button';
        submitClone.className = 'tv-key tv-key-submit';
        submitClone.textContent = 'Submit Password';
        submitClone.addEventListener('click', () => {
          submitButton.click();
        });
        submitRow.appendChild(submitClone);
        keypad.appendChild(submitRow);
      }
    }

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

    async function showLoginModal(authStatus) {
      if (authStatus && typeof authStatus === 'object') {
        loginContext.viewerPasswordRequired = Boolean(authStatus.viewer_password_required);
        loginContext.isTvBrowser = Boolean(authStatus.is_tv_browser);
      }

      const modal = document.getElementById('loginModal');
      const form = document.getElementById('loginForm');
      const accessMsg = document.getElementById('accessMessage');
      const passwordInput = document.getElementById('passwordInput');
      const accessGranted = document.getElementById('accessGranted');
      const dismissBtn = document.getElementById('dismissLoginBtn');
      const clearPasswordBtn = document.getElementById('clearPasswordBtn');
      const submitBtn = form ? form.querySelector('button[type="submit"]') : null;
      const tvInputHint = document.getElementById('tvInputHint');
      const tvKeypad = document.getElementById('tvKeypad');

      if (!modal || !form || !accessMsg || !passwordInput || !accessGranted) {
        return;
      }

      modal.classList.remove('hidden');
      accessMsg.textContent = loginContext.viewerPasswordRequired
        ? 'This dashboard is protected. Enter the viewer, manager, or admin password to continue.'
        : 'This dashboard is protected. External access requires a password.';
      accessMsg.style.color = 'var(--muted)';
      form.style.display = 'flex';
      accessGranted.style.display = 'none';

      if (dismissBtn) {
        dismissBtn.style.display = loginContext.viewerPasswordRequired ? 'none' : 'inline-flex';
      }
      if (clearPasswordBtn) {
        clearPasswordBtn.style.display = 'inline-flex';
      }
      if (tvInputHint) {
        tvInputHint.style.display = loginContext.isTvBrowser ? 'block' : 'none';
      }
      if (tvKeypad) {
        tvKeypad.style.display = loginContext.isTvBrowser ? 'flex' : 'none';
      }

      createTvKeypad(passwordInput, submitBtn);

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
                accessMsg.textContent = loginContext.viewerPasswordRequired
                  ? 'This dashboard is protected. Enter the viewer, manager, or admin password to continue.'
                  : 'This dashboard is protected. External access requires a password.';
              }, 2000);
            }
          } catch (err) {
            console.error('Login failed:', err);
            accessMsg.textContent = 'Connection error. Please try again.';
            accessMsg.style.color = '#f44336';
          }
        });
      }

      if (dismissBtn && !dismissBtn.dataset.bound) {
        dismissBtn.dataset.bound = 'true';
        dismissBtn.addEventListener('click', async (e) => {
          e.preventDefault();
          if (loginContext.viewerPasswordRequired) {
            return;
          }
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

      if (loginContext.isTvBrowser) {
        const firstTvKey = document.querySelector('#tvKeypad .tv-key');
        if (firstTvKey) {
          firstTvKey.focus();
        } else {
          passwordInput.focus();
        }
      } else {
        passwordInput.focus();
      }
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

        loginContext.viewerPasswordRequired = Boolean(authData.viewer_password_required);
        loginContext.isTvBrowser = Boolean(authData.is_tv_browser);

        if (loginContext.viewerPasswordRequired) {
          sessionStorage.removeItem('loginDismissed');
        }

        if (authData.role) {
          sessionStorage.setItem('userRole', authData.role);
        }

        if (authData.authenticated) {
          if (authData.role === 'viewer') {
            sessionStorage.setItem('userRole', 'viewer');
          }
          return true;
        }

        if (!loginContext.viewerPasswordRequired && sessionStorage.getItem('loginDismissed')) {
          sessionStorage.setItem('userRole', 'viewer');
          applyRolePermissions();
          return true;
        }

        await showLoginModal(authData);
        return false;
      } catch (err) {
        console.error('Auth check failed:', err);
        if (!loginContext.viewerPasswordRequired && sessionStorage.getItem('loginDismissed')) {
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
