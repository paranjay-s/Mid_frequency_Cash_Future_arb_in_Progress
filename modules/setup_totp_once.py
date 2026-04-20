#-----------NOTE- ONLY TO BE USED ONCE, IF INSTALLING FOR THE FIRST TIME-------------------


# setup_totp.py
# setup_totp.py
import os
import re
from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv

def main():
    print("=== ONE-TIME TOTP SETUP ===")
    print("Logging into PROD using standard SMS OTP...")
    setup_client = InitNubraSdk(NubraEnv.PROD)

    print("\n[1/3] Generating Secret...")
    secret_response = setup_client.totp_generate_secret()
    
    # Safely extract ONLY the 32-character secret key from the SDK's complex response
    response_str = str(secret_response)
    match = re.search(r'secret_key:([A-Z0-9]+)', response_str)
    
    if match:
        clean_secret = match.group(1)
    elif isinstance(secret_response, dict) and 'data' in secret_response:
        clean_secret = secret_response['data'].get('secret_key', '')
    else:
        print(f"CRITICAL: Could not parse secret from SDK response: {response_str}")
        return

    print(f"\n=== YOUR CLEAN TOTP SECRET ===")
    print(clean_secret)
    print("==============================")
    print("1. Open Google Authenticator (or Authy) on your phone.")
    print("2. Tap '+' and select 'Enter a setup key'.")
    print(f"3. Type this key: {clean_secret}")

    print("\n[2/3] Enabling TOTP on your account...")
    print("⚠️ The SDK will now ask you to verify. Type the 6-digit code from your app.")
    setup_client.totp_enable()

    print("\n[3/3] Saving secret to .env file...")
    with open(".env", "a") as f:
        f.write(f'\nTOTP_SECRET="{clean_secret}"\n')

    print(" Setup complete! Clean TOTP_SECRET appended to .env. You never need to run this again.")

# if __name__ == "__main__":
#     main()