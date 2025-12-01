# ClientX: Teamcenter Session Management

This directory contains the core Python classes for managing a Teamcenter SOA session. It provides a robust, Pythonic wrapper around the .NET `Teamcenter.Soa.Client` libraries.

This is entirely based on the ClientX example Siemens provides in their C# examples.  This hopefully captures the full spirit and intention of the Siemens examples (`Copyright 2022 Siemens Digital Industries Software`) in Python, using the Pythonnet library, 

## Purpose

The `ClientX` module abstracts the complexity of:
1.  **Connecting**: Establishing HTTP or TCCS connections.
2.  **Authenticating**: Handling classic (User/Password) and Single-Sign-On (SSO) login flows.
3.  **Session Persistence**: Managing credentials, session cookies, and re-authentication transparently.
4.  **Error Handling**: Intercepting server errors (500s, connection drops) and offering retry logic.
5.  **Monitoring**: Listening for model changes, partial errors, and logging request/response traffic.

## Key Components

### `Session.py`
The main entry point. It implements a singleton-like pattern to hold the active `Connection`.
- **`Session(host)`**: Initializes the connection.
- **`login()`**: Orchestrates the login process. It attempts a "Classic" login first. If that fails or isn't configured, it attempts an SSO login using tokens provided in environment variables.
- **`logout()`**: Terminates the session.

### `AppXCredentialManager.py`
Implements `Teamcenter.Soa.Client.CredentialManager`.
- **`PromptForCredentials`**: Called by the framework when no credentials are cached. It prompts the user via CLI or uses environment variables (`TCUSER`, `TCPASSWORD`).
- **`GetCredentials`**: Called when the server returns a 401 (Unauthorized) or session timeout. It handles the re-authentication challenge.
- **`SetUserPassword` / `SetGroupRole`**: Caches credentials for silent re-authentication.

### `AppXExceptionHandler.py`
Implements `Teamcenter.Soa.Client.ExceptionHandler`.
- Intercepts `InternalServerException` (e.g., network down, server panic).
- Prompts the user to **Retry** or **Cancel** the last operation, preventing the application from crashing due to transient network issues.

### `AppXPartialErrorListener.py`
Implements `Teamcenter.Soa.Client.Model.PartialErrorListener`.
- Listens for "Partial Errors" in `ServiceData`. These are non-fatal errors (e.g., "Item not found") returned alongside successful data.
- Prints these errors to the console so they aren't silently ignored.

### `AppXModelEventListener.py`
Implements `Teamcenter.Soa.Client.Model.ModelEventListener`.
- Notifies the application when objects in the client-side Data Model Cache are updated or deleted by service calls.

### `AppXRequestListener.py`
Implements `Teamcenter.Soa.Client.RequestListener`.
- Logs every outgoing SOA request (Service + Operation) and incoming response. Useful for debugging traffic flow.

## Usage

```python
from ClientX.Session import Session

# 1. Initialize
sess = Session("http://tcserver:8080/tc")

# 2. Login (Interactive or via Env Vars)
user = sess.login()
if user:
    print(f"Logged in as {user.UserId}")
    
    # ... Perform SOA operations ...

    # 3. Logout
    sess.logout()
```

## Environment Variables

- `TC_URL`: Default host URL.
- `TCUSER`, `TCPASSWORD`: Credentials for classic login.
- `TCGROUP`, `TCROLE`: Optional group/role context.
- `TC_SSO_TOKEN`: Token for SSO login (if classic fails).
- `TC_SSO_APP_ID`, `TC_SSO_LOGIN_URL`: Configuration for SSO.
