# Aligned ClientX login with the 2406 expectations and fixed SSO handling.

  - ClientX/Session.py: Classic login now uses the 2011_06 Credentials object with user/pass/group/role/locale/discriminator per docs
  *  (SessionServiceLogin(Credentials), net/CostCt0/html/24fe8065-9257-0c47-f1e4-559336b578f5.htm; Credentials Fields, net/CostCt0/
  *  html/183f84eb-c355-cc20-b1fa-4ae2f0319566.htm). Locale can come from TC_LOCALE, and the session discriminator uses the manager’s value.
  *  SSO fallback now requires TC_SSO_TOKEN, builds a Credentials object, sets the credential manager to SSO, and calls the documented overload
  *  (SessionServiceLoginSSO(String,…), net/CostCt0/html/600c9b11-82d7-a893-c808-edfba2885268.htm). It downgrades back to classic mode only if SSO fails.
  
  - ClientX/AppXCredentialManager.py: Added proper credential-type switching (STD/SSO) to report the right CredentialType to the framework (CredentialManagerCredentialType Property, net/CostCt0/html/2722dd81-8cfd-1d0d-b03e-8f8cf69138a0.htm). The default session discriminator now comes from  TC_SESSION_DISCRIMINATOR or a generated GUID, matching the doc guidance on unique discriminators.

  **Notes:** set TC_SSO_TOKEN (and optionally TC_SSO_USER, TCGROUP, TCROLE, TC_LOCALE, TC_SESSION_DISCRIMINATOR) before invoking Session(host). Tests not run; please try a classic login and an SSO login with those env vars to validate end-to-end.