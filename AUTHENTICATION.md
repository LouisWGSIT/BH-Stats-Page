# Dashboard Authentication Guide

## Overview
The Warehouse Stats Dashboard now includes a hybrid authentication system designed to provide:
- **Automatic access** for TV displays and devices on your local network
- **Password protection** for external/remote access
- **Flexibility** for managers who need to access from outside the facility

## How It Works

### Local Network Access (Automatic)
Devices connected to your local network are automatically granted access without needing a password. This includes:
- TV displays running the dashboard
- Office computers on the same network
- Any device with IP address in these ranges:
  - `192.168.0.0 - 192.168.255.255` (192.168.x.x)
  - `10.0.0.0 - 10.255.255.255` (10.x.x.x)  
  - `172.16.0.0 - 172.31.255.255` (172.16.x.x)

### External Access (Password Protected)
Users accessing the dashboard from outside the local network will see a login modal requiring a password.

## Setting the Dashboard Password

### Default Password
The default password is: `BHStats2024!`

### Change the Password
To change the password, set the environment variable `DASHBOARD_PASSWORD` on your server:

**On Windows (Command Prompt):**
```batch
set DASHBOARD_PASSWORD=YourNewPassword123!
```

**On Windows (PowerShell):**
```powershell
$env:DASHBOARD_PASSWORD = "YourNewPassword123!"
```

**On Linux/Mac:**
```bash
export DASHBOARD_PASSWORD="YourNewPassword123!"
```

**In Heroku/Deployment:**
Add a config variable:
```bash
heroku config:set DASHBOARD_PASSWORD="YourNewPassword123!"
```

## For Remote Access

Managers who need to access the dashboard from home or outside the facility can:

1. **Visit the dashboard URL** (e.g., `https://your-domain.com/`)
2. **See the login modal** if they're not on the local network
3. **Enter the password** when prompted
4. **Access the dashboard** once authenticated

The password stays valid for the session (if using the same browser).

## Technical Details

### Authentication Flow
1. Frontend loads and checks `/auth/status` endpoint
2. Server examines client IP address
3. If IP is on local network → automatic access
4. If IP is external → show login modal
5. User enters password → `/auth/login` endpoint validates
6. If valid → user gets auth token stored in session
7. Auth token added to all subsequent API requests

### API Authentication
External API calls include the Authorization header:
```
Authorization: Bearer [password]
```

### Password Storage
Passwords are:
- ✅ Checked at runtime, not stored
- ✅ Can be changed via environment variable without code changes
- ✅ Transmitted over HTTPS only (when deployed with SSL)
- ✅ Not visible in browser console or network logs

## Network Configuration

### Finding Your Network Subnet
To verify your local network range, check your device's IP:

**Windows:**
```batch
ipconfig
```
Look for "IPv4 Address" - this tells you your subnet

**Mac/Linux:**
```bash
ifconfig
```

### Whitelisting Additional Networks
If you need to add additional networks to the auto-access list, edit `main.py`:

```python
LOCAL_NETWORKS = [
    ipaddress.ip_network("192.168.0.0/16"),   # Your network 1
    ipaddress.ip_network("10.0.0.0/8"),       # Your network 2
    ipaddress.ip_network("192.168.1.0/24"),   # Add custom subnet here
]
```

CIDR notation: `/24` = 256 IPs, `/16` = 65,536 IPs, `/8` = 16M IPs

## Troubleshooting

### TV/Local Device Still Asks for Password
- **Issue**: Device on local network sees login modal
- **Solution**: Verify device IP is in the correct range (see "Finding Your Network Subnet" above)
- **Alternative**: Contact your network administrator to confirm network configuration

### Forgot the Password
- **Solution 1**: Change via environment variable (see above)
- **Solution 2**: If deployed locally, stop server and restart with new `DASHBOARD_PASSWORD` set

### Password Isn't Working
- **Check**: Make sure you're using the exact password set in the environment variable
- **Debug**: Check browser console for auth error messages
- **Verify**: Server is actually running (check logs)

### External User Can't Access from Home
- **Issue**: Password entered but access denied
- **Check**: Is the server accessible from outside? (firewall, port forwarding)
- **Verify**: Is HTTPS enabled? (highly recommended for password)

## Security Best Practices

1. **Use HTTPS**: Always use SSL/TLS when accessing from outside the network
2. **Change Default Password**: Don't use the default password in production
3. **Complex Password**: Use a mix of letters, numbers, symbols
4. **Rotate Regularly**: Change password quarterly or when someone leaves
5. **Monitor Access**: Check server logs for failed login attempts
6. **Limit Network Access**: Use firewall rules to limit who can reach the server

## Deployment Notes

### Heroku
```bash
heroku config:set DASHBOARD_PASSWORD="YourSecurePassword123!"
heroku restart
```

### Local Server
```bash
export DASHBOARD_PASSWORD="YourSecurePassword123!"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### Docker
Add to Dockerfile:
```dockerfile
ENV DASHBOARD_PASSWORD="YourSecurePassword123!"
```

## Session Management

- Login sessions are **per-browser**, not server-wide
- Closing the browser clears the session (must re-login)
- Different devices need separate logins
- Session tokens **expire when browser closes**

## FAQ

**Q: Can I disable authentication?**  
A: Not recommended for security. But you can set a very simple password and auto-access your network.

**Q: Do TVs need to login every time?**  
A: No - if they're on the local network, they get automatic access on every page load.

**Q: What if I change networks?**  
A: You can adjust the `LOCAL_NETWORKS` in `main.py` or add multiple network ranges for flexibility.

**Q: Is the password sent to the server?**  
A: Yes, but only over HTTPS. Make sure your deployment uses SSL/TLS certificates.

**Q: Can multiple people use the same password?**  
A: Yes, but for audit purposes, consider using different deployment instances with different passwords.

---

For technical support, check `main.py` for the authentication middleware implementation.
