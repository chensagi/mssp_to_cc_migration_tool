import requests
import json, sys, os
import pprint, argparse, logging
from datetime import datetime
from Vision import Vision  # Ensure this is correctly imported from your Vision class file

# Disable warnings for unverified HTTPS requests
requests.packages.urllib3.disable_warnings()

# Define the directory for logs
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
# Ensure the directory exists
os.makedirs(log_dir, exist_ok=True)


# Main log file with date and time
main_log_filename = os.path.join(log_dir, f'mssp_migration_full.log')

# Set up the main logger
logging.basicConfig(filename=main_log_filename, level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

def load_config(filename):
    """Load the JSON configuration from a file."""
    with open(filename, 'r') as file:
        return json.load(file)

def import_mssp_config(vision, config, new_user_password="P@ssw0rd1!", dry_run=False):
    """Import MSSP configuration into Cyber Controller."""
    if vision.login():
        for group in config:
            cc_group_name = (group["Account Name"] + "_" + group["Account OID"])[:31]
            poList = group["Assets"]
            if vision.create_cc_group(cc_group_name, poList, dry_run=dry_run):
                for user in group["Users"]:
                    vision.add_user_to_group(user, cc_group_name, password=new_user_password, dry_run=dry_run)
            else:
                logging.error(f"couldn't create group {cc_group_name}, skipping it completly.")
                print(f"couldn't create group {cc_group_name}, skipping it completly. \n please check the logs and try again.")

def login(url, username, password):
    payload = f'u={username}&p={password}'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    try:
        response = requests.post(url, headers=headers, data=payload, verify=False)
        if response.status_code == 200:
            logging.info("MSSP: Login successful")
            # Extract sessionid from cookies
            sessionid = response.cookies.get('sessionid')
            if sessionid:
                return sessionid
            else:
                logging.info("Session ID not found in cookies")
        else:
            logging.info(f"Login failed with status code {response.status_code}")
    except requests.exceptions.RequestException as e:
        logging.info(f"An error occurred: {e}")
    return None


def fetch_all_accounts(session_id, mssp_address):
    accounts_url = f"https://{mssp_address}/api/accounts/"
    url = accounts_url
    headers = {
        'Cookie': f'sessionid={session_id}',
    }
    response = requests.get(url, headers=headers, verify=False)
    if response.status_code == 200:
        return response.json().get('reply', [])
    return []

def filter_accounts_by_type(accounts, account_type):
    """
    Filters accounts by type and returns the filtered list.

    Parameters:
    - accounts: List of account dictionaries.
    - account_type: The account type to filter by (e.g., 'CustomerAccount').

    Returns:
    - List of filtered account dictionaries.
    """
    filtered_accounts = [account for account in accounts if account.get('_type') == account_type]
    return filtered_accounts


def fetch_assets_for_account(session_id, account_id, mssp_address):
    assets_url = f"https://{mssp_address}/api/assets/"
    url = f"{assets_url}?type=account&id={account_id}"
    headers = {
        'Cookie': f'sessionid={session_id}',
    }
    response = requests.get(url, headers=headers, verify=False)
    if response.status_code == 200:
        return response.json().get('reply', [])
    return []

def fetch_users_for_account(session_id, account_id, mssp_address):
    users_url = f"https://{mssp_address}/api/users/"

    url = f"{users_url}?type=account&id={account_id}"
    headers = {
        'Cookie': f'sessionid={session_id}',
    }
    response = requests.get(url, headers=headers, verify=False)
    if response.status_code == 200:
        return response.json().get('reply', [])
    return []

def filter_users_by_role(users, role):
    """
    Filters users by role and returns the filtered list.

    Parameters:
    - users: List of user dictionaries.
    - role: The role to filter by (e.g., 'user' or 'operator').

    Returns:
    - List of filtered user dictionaries.
    """
    filtered_users = [user for user in users if user.get('role') == role]
    return filtered_users


def select_new_role(current_roles):
    """
    Selects a new role for the user based on the corrected hierarchy:
    User-Admin (userAdmin) > User-Basic (basicUser) > User-Monitor/User-Viewer (dashboardUser/userViewer)

    Parameters:
    - current_roles: List of roles the user currently has.

    Returns:
    - str: The new role for the user.
    """
    # Updated role hierarchy and mapping with corrected order
    new_role_mapping = {
        'userAdmin': 'MSSP_PORTAL_ADMIN',
        'basicUser': 'MSSP_PORTAL_USER',
        'dashboardUser': 'MSSP_PORTAL_VIEWER',  # dashboardUser and userViewer have the same priority, but come after basicUser
        'userViewer': 'MSSP_PORTAL_VIEWER'
    }

    # Order of priority based on corrected hierarchy
    role_priority = ['userAdmin', 'basicUser', 'dashboardUser', 'userViewer']

    for role in role_priority:
        if role in current_roles:
            return new_role_mapping[role]

    return None  # Return None if no roles match

def build_users_info(filtered_users):
    """
    Builds a list of users with selected information, including their roles from currentAccount,
    allowed IP addresses, 'notes', and determines the new role based on these roles.

    Parameters:
    - filtered_users: A list of user objects, each being a dict with user details.

    Returns:
    - list: A list where each item is a dict of user info including the new role, allowed IPs, and notes.
    """
    users_info = []

    for user in filtered_users:
        username = user.get('username', 'N/A')
        account_oid = user.get('account', {}).get('_oid', 'N/A')
        current_account_roles = user.get('roles', {}).get('currentAccount', [])
        roles_string = ', '.join(current_account_roles) if current_account_roles else 'None'
        new_role = select_new_role(current_account_roles)  # Determine the new role based on the current roles
        allowed_ips = user.get('auth_meta', {}).get('allowed_ip_list', [])
        first_ip = allowed_ips[0] if allowed_ips else ''
        notes = user.get('notes', '')  # Retrieve notes, default to empty string if not present

        user_info = {
            "Name": user.get('name'),
            "Username": username,
            "Role": user.get('role', 'N/A'),  # Original role if specified
            "Email": user.get('email'),
            "Auth Type": user.get('auth_type'),
            "Account OID": account_oid,
            "Role (Current)": roles_string,
            "New Role": new_role,
            "Allowed IP Address": first_ip,  # Convert list of IPs to string
            "Notes": notes  # Add notes to the user info
        }

        users_info.append(user_info)

    return users_info

def build_assets_info(assets):
    """
    Constructs a dictionary for each asset with detailed information.

    Parameters:
    - assets: A list of asset dictionaries.

    Returns:
    - list: A list of dictionaries, each representing an asset's detailed information.
    """
    assets_info_list = []

    for asset in assets:        
        # List approach
        assets_info_list.append(", ".join(asset.get('policies', [])))

    return assets_info_list

def build_structured_export(session_id, mssp_address):
    all_accounts_info = []
    accounts = filter_accounts_by_type(fetch_all_accounts(session_id, mssp_address),'CustomerAccount')
    
    for account in accounts:
        account_id = account.get('_id', {}).get('_oid', 'N/A')
        
        # Fetch additional account details
        account_name = account.get('name', 'N/A')
        account_type = account.get('_type', 'N/A')
        
        # Fetch and process assets and users for the account
        assets = fetch_assets_for_account(session_id, account_id, mssp_address)
        users = filter_users_by_role(fetch_users_for_account(session_id, account_id, mssp_address),'user')
        clean_assets = build_assets_info(assets)
        clean_users = build_users_info(users)
        
        # Process services information (if needed)
        services_info = []
        for service in account.get('services', []):
            services_info.append({
                "Type": service.get('service_type', 'N/A'),
                "Status": service.get('status', 'N/A')
            })
        
        # Compile detailed account information
        account_details = {
            "Account Name": account_name,
            "Type": account_type,
            "Account OID": account_id,
            #"Services": services_info,
            "Assets": clean_assets,
            "Users": clean_users
        }
        
        all_accounts_info.append(account_details) 
    
    return all_accounts_info

def save_data_to_json_file(data, base_filename="export"):
    """
    Saves given data to a JSON file with the current date appended before the file extension.

    Parameters:
    - data: The data to save (e.g., dictionary or list).
    - base_filename: The base name of the file without the extension.
    """
    # Define the directory for config files
    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
    # Ensure the directory exists
    os.makedirs(config_dir, exist_ok=True)

    # Format the current date
    current_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    # Append the current date before the .json extension
    filename = os.path.join(config_dir, f"{base_filename}_{current_date}.json")
    
    with open(filename, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MSSP to CC Configuration Migration Tool')
    parser.add_argument('--mssp-address', required=False, help='IP/FQDN address of the MSSP portal')
    parser.add_argument('--mssp-username', required=False, help='MSSP login username')
    parser.add_argument('--mssp-password', required=False, help='MSSP login password')
    parser.add_argument('--cc-address', required=False, help='IP/FQDN address of the Cyber Controller')
    parser.add_argument('--cc-username', required=False, help='Username for the Cyber Controller')
    parser.add_argument('--cc-password', required=False, help='Password for the Cyber Controller')
    parser.add_argument('--export-file', required=False, help='Filename to save exported MSSP configuration, if not importing directly')
    parser.add_argument('--import-from-file', action='store_true', help='Set this flag to import configuration from a file instead of directly exporting from MSSP')
    parser.add_argument('--config-file', required=False, help='Path to the configuration JSON file for import, required if --import-from-file is set')
    parser.add_argument('--dry-run', action='store_true', help='Run in dry-run mode without making actual changes')
    parser.add_argument('--initial-user-password', required=False, help='Override default password, affects all users configured during migration. Initial default is P@ssw0rd1!')

    # sys.argv = [
    #     'mssp_migrate_to_cc.py',  # Script name
    #     '--mssp-address', '10.26.45.16',
    #     '--mssp-username', 'admin@local.com',
    #     '--mssp-password', 'password',
    #     '--cc-address', '172.17.154.101',
    #     '--cc-username', 'username',
    #     '--cc-password', 'password',
    #     #'--config-file', 'solution\config\export_2024-02-22_16-46-54.json',
    #     #'--import-from-file'
    # ]

    try:
        args = parser.parse_args()
    except SystemExit as e:
        # Log the error
        logging.error("Error parsing arguments.")

        # Print a custom error message and the help message from argparse
        logging.info("Error: Failed to parse the arguments. Please check the input arguments.")
        parser.print_help()

        sys.exit(e.code)

    # Direct export from MSSP and import to CC
    if not args.import_from_file:
        if not all([args.mssp_address, args.mssp_username, args.mssp_password]):
            parser.error("When not importing from a file, the following arguments are required: --mssp-address, --mssp-username, --mssp-password")
        
        # Login to MSSP and fetch data
        session_id = login(f"https://{args.mssp_address}/api/auth/", args.mssp_username, args.mssp_password)
        if session_id:
            structured_export = build_structured_export(session_id, args.mssp_address)
            # Optionally save to file
            if args.export_file:
                save_data_to_json_file(structured_export, args.export_file)
                logging.info(f"Exported MSSP configuration saved to {args.export_file}")
            config = structured_export
        else:
            logging.info("Failed to log in to MSSP.")
            exit(1)
    else:
        # Load configuration from file
        if not args.config_file:
            logging.info("Config file path is required when importing from file.")
            exit(1)
        config = load_config(args.config_file)

    # Check if cc_ip, cc_username, and cc_password are provided
    if args.cc_address and args.cc_username and args.cc_password:
        # Initialize Vision instance and import configuration to CC
        vision = Vision(args.cc_address, args.cc_username, args.cc_password)
        if not args.export_file:
            if not args.initial_user_password:
                import_mssp_config(vision, config, dry_run=args.dry_run)
            else:
                import_mssp_config(vision, config, new_user_password=args.initial_user_password, dry_run=args.dry_run)
    elif args.dry_run:
        logging.info("Warning: dry run was requested but some or all of the following args are missing: CC IP address, CC username, CC password.")
