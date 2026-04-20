
# modules/auth.py
# modules/auth.py
import os
import builtins
import getpass
import pyotp
from unittest.mock import patch
from dotenv import load_dotenv
from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv

def authenticate_nubra(env):
    """
    Performs one-time authentication and returns the Nubra SDK instance.
    Fully automated: Bypasses terminal prompts using pyotp and .env.
    """
    load_dotenv()
    
    # 1. Verify we have the credentials
    secret = os.getenv("TOTP_SECRET")
    if not secret:
        raise ValueError("CRITICAL: TOTP_SECRET not found in .env. Run setup_totp.py first.")

    # 2. Generate the live 6-digit code
    live_totp_code = pyotp.TOTP(secret).now()
    
    # Save original input functions so we don't permanently break Python's input
    original_input = builtins.input
    original_getpass = getpass.getpass

    # 3. Intercept the SDK's prompts
    def automated_input(prompt=""):
        prompt_lower = prompt.lower()
        # If the SDK asks for a code, intercept and return the pyotp code
        if "totp" in prompt_lower or "code" in prompt_lower or "otp" in prompt_lower:
            print(f"{prompt} [AUTO-FILLED BY PYOTP: {live_totp_code}]")
            return live_totp_code
        return original_input(prompt)
        
    def automated_getpass(prompt=""):
        prompt_lower = prompt.lower()
        if "totp" in prompt_lower or "code" in prompt_lower or "otp" in prompt_lower:
            print(f"{prompt} [AUTO-FILLED BY PYOTP: {live_totp_code}]")
            return live_totp_code
        return original_getpass(prompt)

    print(f"[AUTH] Initializing SDK for {env.name} with fully automated TOTP...")
    
    # 4. Apply the monkeypatch just for the duration of the login
    with patch("builtins.input", automated_input), patch("getpass.getpass", automated_getpass):
        # env_creds=True pulls PHONE_NO and MPIN from .env
        # totp_login=True tells the SDK to look for the TOTP code
        return InitNubraSdk(
            env, 
            env_creds=True, 
            totp_login=True
        )