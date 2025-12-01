"""
Script to query Teamcenter Items by creation date and fetch their properties,
including Item Master and latest Item Revision.

The output is written to a JSON file, including UIDs for further processing.

Usage:
    python get_items_by_date.py --start YYYY-MM-DD --end YYYY-MM-DD --output output.json [--host http://tc-server:port/tc]
"""

import argparse
import datetime
import os
import sys
import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Setup sys.path to ensure we can import local modules from the parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env file in the parent directory
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path=env_path)

try:
    import tc_utils
    from ClientX.Session import Session
except ImportError as e:
    print(f"Error importing required modules: {e}")
    sys.exit(1)

# .NET Imports
import clr
import System  # type: ignore
from System import Array, String  # type: ignore
from Teamcenter.Services.Strong.Core import DataManagementService, SessionService  # type: ignore
from Teamcenter.Services.Strong.Query import SavedQueryService  # type: ignore
from Teamcenter.Services.Strong.Query._2008_06 import SavedQuery as SavedQuery2008  # type: ignore
from Teamcenter.Services.Strong.Query._2010_04 import SavedQuery as SavedQuery2010  # type: ignore
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore
from Teamcenter.Soa.Client.Model.Strong import ImanQuery  # type: ignore
from Teamcenter.Soa.Common import ObjectPropertyPolicy  # type: ignore


def parse_args() -> argparse.Namespace:
    """
    Parses command-line arguments.

    Returns:
        argparse.Namespace: The parsed arguments containing start/end dates, output file, and credentials.
    """
    parser = argparse.ArgumentParser(description="Query Teamcenter Items by date range.")
    parser.add_argument("--start", required=True, help="Start date (inclusive) in YYYY-MM-DD format")
    parser.add_argument("--end", required=True, help="End date (inclusive) in YYYY-MM-DD format")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    
    # Credentials and Host defaults from .env
    default_host = os.getenv("TC_URL", "http://localhost:8080/tc")
    default_user = os.getenv("TCUSER")
    default_password = os.getenv("TCPASSWORD")

    parser.add_argument("--host", default=default_host, help="Teamcenter Host URL")
    parser.add_argument("--user", default=default_user, help="Teamcenter Username")
    parser.add_argument("--password", default=default_password, help="Teamcenter Password")
    
    return parser.parse_args()


def format_date_for_tc(date_str: str) -> str:
    """
    Converts YYYY-MM-DD to dd-MMM-yyyy HH:mm format (e.g., 23-Nov-2025 00:00).

    Args:
        date_str (str): The date string in YYYY-MM-DD format.

    Returns:
        str: The formatted date string for Teamcenter queries (dd-MMM-yyyy HH:mm).

    Raises:
        SystemExit: If the date format is invalid.
    """
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d-%b-%Y 00:00")
    except ValueError:
        print(f"Error: Invalid date format {date_str}. Use YYYY-MM-DD.")
        sys.exit(1)


def find_general_query(query_service: SavedQueryService) -> Optional[ModelObject]:
    """
    Finds the 'General...' saved query in Teamcenter.

    Uses the `Teamcenter.Services.Strong.Query.SavedQueryService.FindSavedQueries` method.

    Args:
        query_service (SavedQueryService): The initialized SavedQueryService instance.

    Returns:
        Optional[ModelObject]: The 'General...' query object (typically an ImanQuery) if found, else None.
    """
    criteria = SavedQuery2010.FindSavedQueriesCriteriaInput()
    criteria.QueryNames = Array[String](["General..."])
    criteria.QueryType = 0 # 0 = Local Query

    try:
        response = query_service.FindSavedQueries(Array[SavedQuery2010.FindSavedQueriesCriteriaInput]([criteria]))
        if response.SavedQueries:
            return response.SavedQueries[0]
    except Exception as e:
        print(f"Error finding query: {e}")
    return None


def get_query_entries(query_service: SavedQueryService, query_obj: ModelObject) -> List[str]:
    """
    Describes the saved query to retrieve its entry names (search criteria fields).

    Uses `Teamcenter.Services.Strong.Query.SavedQueryService.DescribeSavedQueries`.

    Args:
        query_service (SavedQueryService): The initialized SavedQueryService instance.
        query_obj (ModelObject): The saved query object (ImanQuery) to describe.

    Returns:
        List[str]: A list of entry names available for the query (e.g., 'Type', 'Created After').
    """
    try:
        # The service expects ImanQuery[], so we must cast/use the correct array type
        # query_obj is typically ModelObject but needs to be treated as ImanQuery
        response = query_service.DescribeSavedQueries(Array[ImanQuery]([query_obj]))
        
        # Response has 'FieldLists' (array of SavedQueryFieldListObject), not 'Descriptions'
        if response.FieldLists:
            field_list = response.FieldLists[0]
            entries = []
            if field_list.Fields:
                for field in field_list.Fields:
                    entries.append(field.EntryName)
            return entries
    except Exception as e:
        print(f"Error describing query: {e}")
    return []


def execute_query(query_service: SavedQueryService, query_obj: ModelObject, criteria_map: Dict[str, str]) -> List[str]:
    """
    Executes the saved query with the given criteria.

    Uses `Teamcenter.Services.Strong.Query.SavedQueryService.ExecuteSavedQueries`.

    Args:
        query_service (SavedQueryService): The initialized SavedQueryService instance.
        query_obj (ModelObject): The saved query object to execute.
        criteria_map (Dict[str, str]): A dictionary mapping query entry names to their values.
            Minimum required entries depend on the query definition, but usually include:
            - Type (e.g., "Item")
            - Search criteria (e.g., "Created After": "...")

    Returns:
        List[str]: A list of Object UIDs matching the query. Returns an empty list on error or no results.
    """
    query_input = SavedQuery2008.QueryInput()
    query_input.Query = query_obj
    query_input.MaxNumToReturn = 0 # No limit
    query_input.ResultsType = 0 # Standard result

    entries = []
    values = []
    
    for key, val in criteria_map.items():
        entries.append(key)
        values.append(val)

    query_input.Entries = Array[String](entries)
    query_input.Values = Array[String](values)

    try:
        response = query_service.ExecuteSavedQueries(Array[SavedQuery2008.QueryInput]([query_input]))
        
        if response.ServiceData.sizeOfPartialErrors() > 0:
            for i in range(response.ServiceData.sizeOfPartialErrors()):
                err = response.ServiceData.GetPartialError(i)
                for msg in err.ErrorValues:
                    print(f"Query Error: {msg.Message}")
            return []
        
        if response.ArrayOfResults:
            # ArrayOfResults is an array of QueryResults
            # QueryResults has 'ObjectUIDS' (string[])
            results = response.ArrayOfResults[0]
            if results.ObjectUIDS:
                return list(results.ObjectUIDS)
    except Exception as e:
        print(f"Error executing query: {e}")
    
    return []


def _bulk_load(dm_service: DataManagementService, uids: List[str]) -> List[ModelObject]:
    """
    Helper function to bulk load objects by UID in chunks.

    Uses `Teamcenter.Services.Strong.Core.DataManagementService.LoadObjects`.

    Args:
        dm_service (DataManagementService): The initialized DataManagementService instance.
        uids (List[str]): A list of UIDs to load.

    Returns:
        List[ModelObject]: A list of loaded ModelObjects.
    """
    chunk_size = 500 
    loaded_objects = []
    
    for i in range(0, len(uids), chunk_size):
        chunk = uids[i:i + chunk_size]
        try:
             resp = dm_service.LoadObjects(Array[String](chunk))
             if resp.sizeOfPartialErrors() > 0:
                 print(f"    Warning: Partial errors loading chunk {i}")
                 
             for j in range(resp.sizeOfPlainObjects()):
                 loaded_objects.append(resp.GetPlainObject(j))
        except Exception as e:
            print(f"    Error loading chunk {i}: {e}")
            
    return loaded_objects

def load_items_and_related(dm_service: DataManagementService, uids: List[str]) -> List[ModelObject]:
    """
    Loads Item properties and then bulk-loads related ItemMaster and ItemRevision objects
    to avoid N+1 server calls.

    Uses `Teamcenter.Services.Strong.Core.DataManagementService` and `ObjectPropertyPolicy`.

    Args:
        dm_service (DataManagementService): The initialized DataManagementService instance.
        uids (List[str]): A list of Item UIDs to load.

    Returns:
        List[ModelObject]: The loaded Item objects with their properties populated according to the policy.
    """
    if not uids:
        return []

    # 1. Define Policy
    policy = ObjectPropertyPolicy()
    # Define which properties to load for each business object type.
    # This policy ensures that when objects of these types are loaded (e.g., 'Item', 'ItemMaster', 'ItemRevision'),
    # the specified properties are populated, avoiding additional server calls for each property.
    policy.AddType("Item", Array[String](["item_id", "object_name", "item_master_tag", "revision_list"]))
    policy.AddType("WorkspaceObject", Array[String](["object_name"]))
    # These types will be used when we load the related objects
    policy.AddType("ItemMaster", Array[String](["object_name"]))
    policy.AddType("ItemRevision", Array[String](["item_revision_id", "object_name", "creation_date", "release_status_list"]))
    policy.AddType("ReleaseStatus", Array[String](["object_name"]))
    
    conn = Session.getConnection()
    if conn:
        # Register and set the policy. Setting an ObjectPropertyPolicy is crucial
        # to instruct the Teamcenter server to return specific properties for
        # business objects (like Item, ItemMaster, ItemRevision) when they are loaded.
        # Without this, only default properties would be available, potentially leading
        # to missing data for item_id, revision_list, object_name, etc.
        policy_name = conn.ObjectPropertyPolicyManager.AddPolicy(policy, True)
        conn.ObjectPropertyPolicyManager.SetPolicy(policy_name)
        
        # Force refresh from DB to ensure properties are loaded per the new policy
        session_service = SessionService.getService(conn)
        if session_service:
            session_service.RefreshPOMCachePerRequest(True)

    # 2. Load Items
    print(f"  Loading {len(uids)} Items...")
    items = _bulk_load(dm_service, uids)

    # 3. Collect Related UIDs
    related_uids = set()
    for item in items:
        try:
            # Item Master
            im_prop = item.GetProperty("item_master_tag")
            if im_prop and im_prop.ModelObjectValue:
                related_uids.add(im_prop.ModelObjectValue.Uid)
            
            # Revisions
            revs_prop = item.GetProperty("revision_list")
            if revs_prop and revs_prop.ModelObjectArrayValue:
                for rev in revs_prop.ModelObjectArrayValue:
                    related_uids.add(rev.Uid)
        except Exception:
            pass
            
    # 4. Load Related Objects
    if related_uids:
        print(f"  Loading {len(related_uids)} related objects (Masters & Revisions)...")
        loaded_related = _bulk_load(dm_service, list(related_uids))
        
        # Explicitly refresh ItemRevisions to ensure release_status_list is loaded
        revisions_to_refresh = []
        for obj in loaded_related:
            if "ItemRevision" in obj.GetType().Name:
                revisions_to_refresh.append(obj)
        
        if revisions_to_refresh:
            print(f"  Refreshing {len(revisions_to_refresh)} revisions to ensure properties loaded...")
            chunk_size = 100
            for i in range(0, len(revisions_to_refresh), chunk_size):
                chunk = revisions_to_refresh[i:i + chunk_size]
                try:
                    dm_service.RefreshObjects(Array[ModelObject](chunk))
                except Exception as e:
                    print(f"    Error refreshing revisions chunk {i}: {e}")

            # Collect and refresh ReleaseStatus objects
            statuses_to_refresh = set()
            for rev in revisions_to_refresh:
                try:
                    rs_prop = rev.GetProperty("release_status_list")
                    if rs_prop and rs_prop.ModelObjectArrayValue:
                        for status in rs_prop.ModelObjectArrayValue:
                            statuses_to_refresh.add(status)
                except Exception:
                    pass
            
            if statuses_to_refresh:
                status_list = list(statuses_to_refresh)
                print(f"  Refreshing {len(status_list)} ReleaseStatus objects...")
                for i in range(0, len(status_list), chunk_size):
                    chunk = status_list[i:i + chunk_size]
                    try:
                        dm_service.RefreshObjects(Array[ModelObject](chunk))
                    except Exception as e:
                        print(f"    Error refreshing status chunk {i}: {e}")
        
    return items


def main() -> None:
    """
    Main execution function.
    - Connects to Teamcenter.
    - Finds the 'General...' query.
    - Identifies query parameters for searching Items by creation date.
    - Executes the query.
    - Bulk loads the results and their related objects (Master, Revisions).
    - Writes the output to a JSON file.
    """
    args = parse_args()
    
    # 1. Initialize Session
    session = Session(args.host)

    # 2. Configure CredentialManager explicitly
    # This avoids relying on environment variable fallback in PromptForCredentials
    # and matches the pattern used in get_drawings.py
    cred_mgr = Session.credentialManager
    
    # Use provided arguments (which default to .env values)
    if args.user:
        cred_mgr.name = args.user
    if args.password:
        cred_mgr.password = args.password
        
    # Set Group/Role if they exist in the environment, similar to the main app
    group = os.getenv("TC_GROUP") or os.getenv("TCGROUP") or ""
    role = os.getenv("TC_ROLE") or os.getenv("TCROLE") or ""
    if group or role:
        cred_mgr.SetGroupRole(group, role)

    # 3. Login
    user = session.login()
    if not user:
        print("Login failed.")
        sys.exit(1)

    # 2. Get Services
    conn = Session.getConnection()
    query_service = SavedQueryService.getService(conn)
    dm_service = DataManagementService.getService(conn)

    # 3. Find 'General...' Query
    print("Finding 'General...' query...")
    general_query = find_general_query(query_service)
    if not general_query:
        print("Could not find 'General...' saved query.")
        session.logout()
        sys.exit(1)

    # 4. Inspect Entries to match "Created After" etc.
    entries = get_query_entries(query_service, general_query)
    
    type_entry = next((e for e in entries if "Type" in e or "type" in e), None)
    
    # Refine search for "Created" specifically - handling potential spacing/case variations
    created_after_entry = next((e for e in entries if "Created" in e and "After" in e), None)
    created_before_entry = next((e for e in entries if "Created" in e and "Before" in e), None)

    # Fallback if exact match fails (maybe localized)
    if not (type_entry and created_after_entry and created_before_entry):
        print("Could not identify required query entries (Type, Created After, Created Before).")
        print(f"Available entries: {entries}")
        session.logout()
        sys.exit(1)

    print(f"Using Query: {general_query.Query_name}")
    print(f"Entries: {type_entry}, {created_after_entry}, {created_before_entry}")

    # 5. Execute Query
    start_date_tc = format_date_for_tc(args.start)
    end_date_tc = format_date_for_tc(args.end)
    
    criteria = {
        type_entry: "Item", # Searching for Items
        created_after_entry: start_date_tc,
        created_before_entry: end_date_tc
    }
    
    print(f"Executing query with criteria: {criteria}")
    uids = execute_query(query_service, general_query, criteria)
    print(f"Found {len(uids)} items.")

    if not uids:
        session.logout()
        sys.exit(0)

    # 6. Load and Process Items
    print("Loading properties...")
    items = load_items_and_related(dm_service, list(uids))
    
    results = []

    for item in items:
        try:
            # Item Props
            item_id = item.GetPropertyDisplayableValue("item_id")
            name = item.GetPropertyDisplayableValue("object_name")
            item_uid = item.Uid
            
            # Item Master
            item_master_data = None
            im_prop = item.GetProperty("item_master_tag")
            if im_prop and im_prop.ModelObjectValue:
                 im_obj = im_prop.ModelObjectValue
                 item_master_data = {
                     "uid": im_obj.Uid,
                     "object_name": im_obj.GetPropertyDisplayableValue("object_name")
                 }

            # Latest Revision
            latest_rev_data = None
            revs_prop = item.GetProperty("revision_list")
            if revs_prop and revs_prop.ModelObjectArrayValue:
                revs = revs_prop.ModelObjectArrayValue
                if revs:
                    # Assuming last is latest
                    last_rev = revs[-1]
                    
                    release_statuses: List[str] = []
                    # Retrieve release status list
                    # .NET Call: ModelObject.GetProperty("release_status_list")
                    release_status_prop = last_rev.GetProperty("release_status_list")
                    if release_status_prop and release_status_prop.ModelObjectArrayValue:
                        # Iterate through each ReleaseStatus ModelObject and get its object_name
                        for status_obj in release_status_prop.ModelObjectArrayValue:
                            try:
                                release_statuses.append(status_obj.GetPropertyDisplayableValue("object_name"))
                            except Exception:
                                pass # Ignore if name not loaded or other error
                                
                    if not release_statuses:
                        # Skip items that have no release status
                        continue

                    # Use the last status in the list (assumed to be the most relevant)
                    last_release_status = release_statuses[-1]

                    # Filter: Only include items with "Released" status
                    if last_release_status != "Released":
                        continue

                    latest_rev_data = {
                        "uid": last_rev.Uid,
                        "item_revision_id": last_rev.GetPropertyDisplayableValue("item_revision_id"),
                        "object_name": last_rev.GetPropertyDisplayableValue("object_name"),
                        "creation_date": last_rev.GetPropertyDisplayableValue("creation_date"),
                        "release_status": last_release_status
                    }

            results.append({
                "item_id": item_id,
                "uid": item_uid,
                "object_name": name,
                "item_master": item_master_data,
                "latest_revision": latest_rev_data
            })

        except Exception as e:
            print(f"Error processing item {item}: {e}")

    # 7. Write JSON
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        print(f"Successfully wrote {len(results)} items to {args.output}")
    except Exception as e:
        print(f"Error writing output file: {e}")

    session.logout()


if __name__ == "__main__":
    main()