"""
Script to query Teamcenter for 'Where Used' information based on an input JSON file.

The input JSON should contain a list of items (as produced by get_items_by_date.py).
For each input item, the script queries Teamcenter to find where it is used (parents).
It returns the latest revision of the parent objects.

Usage:
    python get_where_used.py --input input.json --output output.json [--host http://tc-server:port/tc]
"""

import argparse
import os
import sys
import json
from typing import List, Dict, Any, Optional, Set
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
from System import Array, String, Boolean, Int32, Exception as NetException  # type: ignore
from System.Collections import Hashtable # type: ignore
from Teamcenter.Services.Strong.Core import DataManagementService, SessionService  # type: ignore
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore
from Teamcenter.Soa.Common import ObjectPropertyPolicy  # type: ignore

# Import specific version for WhereUsed types
# Note: Namespaces in Pythonnet roughly match .NET namespaces.
# We try to import the _2012_02 DataManagement namespace for WhereUsedInputData
try:
    from Teamcenter.Services.Strong.Core._2012_02 import DataManagement as DM_2012  # type: ignore
except ImportError:
    DM_2012 = None
    print("Warning: Could not import Teamcenter.Services.Strong.Core._2012_02.DataManagement. 'WhereUsed' might fail.")


def parse_args() -> argparse.Namespace:
    """
    Parses command-line arguments.

    Returns:
        argparse.Namespace: The parsed arguments containing:
            - input: Path to input JSON file.
            - output: Path to output JSON file.
            - host: Teamcenter host URL.
            - user: Teamcenter username.
            - password: Teamcenter password.
            - parent_type: Comma-separated string of parent types to filter by.
    """
    parser = argparse.ArgumentParser(description="Query Teamcenter Where-Used.")
    parser.add_argument("--input", required=True, help="Input JSON file path (list of items)")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    
    # Credentials and Host defaults from .env
    default_host = os.getenv("TC_URL", "http://localhost:8080/tc")
    default_user = os.getenv("TCUSER")
    default_password = os.getenv("TCPASSWORD")

    parser.add_argument("--host", default=default_host, help="Teamcenter Host URL")
    parser.add_argument("--user", default=default_user, help="Teamcenter Username")
    parser.add_argument("--password", default=default_password, help="Teamcenter Password")
    parser.add_argument("--parent-type", help="Comma-separated list of Teamcenter Types to filter parents by (e.g. 'ItemRevision, Design Revision')")
    
    return parser.parse_args()


def _bulk_load(dm_service: DataManagementService, uids: List[str]) -> List[ModelObject]:
    """
    Helper function to bulk load objects by UID in chunks.

    This function avoids hitting SOA limits by splitting the list of UIDs into smaller chunks.
    It calls `DataManagementService.LoadObjects` for each chunk.

    Args:
        dm_service (DataManagementService): The Teamcenter DataManagement service instance.
        uids (List[str]): A list of Teamcenter UIDs to load.

    Returns:
        List[ModelObject]: A list of loaded Teamcenter ModelObjects.
    """
    chunk_size = 500 
    loaded_objects: List[ModelObject] = []
    
    # Dedup UIDs
    unique_uids = list(set(uids))
    
    for i in range(0, len(unique_uids), chunk_size):
        chunk = unique_uids[i:i + chunk_size]
        try:
             # .NET Call: DataManagementService.LoadObjects(String[] uids)
             # Loads the specified objects from the database.
             # Returns a ServiceData object containing the loaded objects (PlainObjects) and any errors.
             resp = dm_service.LoadObjects(Array[String](chunk))
             
             tc_utils.CheckServiceData(resp)
                 
             for j in range(resp.sizeOfPlainObjects()):
                 loaded_objects.append(resp.GetPlainObject(j))
        except Exception as e:
            print(f"    Error loading chunk {i}: {e}")
            
    return loaded_objects


def load_target_objects(dm_service: DataManagementService, input_data: List[Dict[str, Any]]) -> Dict[str, ModelObject]:
    """
    Loads the target objects (Item Revisions) from the input data.

    Identifies the correct UID to query (preferably the latest revision UID, otherwise the item UID)
    from the input JSON list and loads the corresponding ModelObjects.

    Args:
        dm_service (DataManagementService): The Teamcenter DataManagement service instance.
        input_data (List[Dict[str, Any]]): List of item dictionaries from the input JSON.

    Returns:
        Dict[str, ModelObject]: A map of {object_uid: ModelObject}.
    """
    uids_to_load: List[str] = []

    for entry in input_data:
        # Prefer latest_revision UID, fallback to item UID
        target_uid = None
        if "latest_revision" in entry and entry["latest_revision"] and "uid" in entry["latest_revision"]:
            target_uid = entry["latest_revision"]["uid"]
        elif "uid" in entry:
            target_uid = entry["uid"]
        
        if target_uid:
            uids_to_load.append(target_uid)
            
    if not uids_to_load:
        return {}

    print(f"Loading {len(uids_to_load)} target objects for Where-Used query...")
    # Bulk load the identified objects
    loaded_objs = _bulk_load(dm_service, uids_to_load)
    
    return {obj.Uid: obj for obj in loaded_objs}

def perform_where_used(dm_service: DataManagementService, targets: List[ModelObject]) -> Dict[str, List[str]]:
    """
    Performs 'Where Used' analysis using the Teamcenter Services Strong Core _2012_02 API.

    Documentation Reference:
    - Namespace: Teamcenter.Services.Strong.Core._2012_02.DataManagement
    - Method: WhereUsed(WhereUsedInputData[] Input, WhereUsedConfigParameters ConfigParams)
    - Input Struct: WhereUsedInputData
        - ClientId (string): Unique identifier for the input.
        - InputObject (ModelObject): The target object (Item/ItemRevision).
        - UseLocalParams (bool): If true, uses InputParams field. If false, uses the common ConfigParams passed to the method.
    - Config Struct: WhereUsedConfigParameters
        - IntMap (Map<string, int>): Configuration integers. Key 'numLevels' controls depth.
        - BoolMap (Map<string, bool>): Configuration booleans. Key 'whereUsedPreciseFlag' controls precise/imprecise search.
        - TagMap (Map<string, ModelObject>): Key 'revision_rule' can specify a RevisionRule object.

    Args:
        dm_service (DataManagementService): The Teamcenter DataManagement service instance.
        targets (List[ModelObject]): List of target objects (usually Item Revisions) to check usage for.

    Returns:
        Dict[str, List[str]]: A dictionary mapping target UID -> List of Parent UIDs.
    """
    if not targets:
        return {}
    
    if DM_2012 is None:
         print("Error: Teamcenter.Services.Strong.Core._2012_02.DataManagement not loaded. Cannot use new API.")
         return {}

    print(f"Executing Where-Used on {len(targets)} objects (New Method)...")
    
    results: Dict[str, List[str]] = {t.Uid: [] for t in targets}
    
    chunk_size = 50
    
    for i in range(0, len(targets), chunk_size):
        chunk_targets = targets[i:i + chunk_size]
        print(f"  Processing batch {i} to {i + len(chunk_targets)}...")
        
        inputs = []
        for idx, t in enumerate(chunk_targets):
            # .NET Struct: WhereUsedInputData
            # Defines the input for the WhereUsed operation (Target Object, ClientId, etc.)
            # Fields:
            #   ClientId: String identifier
            #   InputObject: The ModelObject to search for
            #   UseLocalParams: Boolean to toggle local vs global config
            wuid = DM_2012.WhereUsedInputData()
            wuid.InputObject = t
            # ClientId must be unique for each input in the request to map results back correctly if needed
            wuid.ClientId = f"Gemini_{i + idx}"
            wuid.UseLocalParams = False
            inputs.append(wuid)
            
        input_arr = Array[DM_2012.WhereUsedInputData](inputs)
        
        # .NET Struct: WhereUsedConfigParameters
        # Configures the depth and precision of the query.
        config = DM_2012.WhereUsedConfigParameters()
        
        # Initialize all maps to avoid nulls (SOA best practice, avoiding NullReferenceException on server side)
        config.IntMap = Hashtable()
        config.BoolMap = Hashtable()
        config.StringMap = Hashtable()
        config.TagMap = Hashtable()
        config.DateMap = Hashtable()
        config.DoubleMap = Hashtable()
        config.FloatMap = Hashtable()
        
        # Populate required config with explicit .NET types
        # numLevels: 1 = Immediate parents only. 0 or -1 might imply all levels depending on version, usually positive int.
        config.IntMap["numLevels"] = Int32(1) 
        # whereUsedPreciseFlag: False = Imprecise (Any revision of parent uses this?). True = Precise (Specific parent revision).
        config.BoolMap["whereUsedPreciseFlag"] = Boolean(False) 
        
        try:
            # .NET Call: DataManagementService.WhereUsed(WhereUsedInputData[], WhereUsedConfigParameters)
            # Performs the Where Used analysis.
            # Returns WhereUsedResponse containing Output (WhereUsedOutputData[]) and ServiceData.
            response = dm_service.WhereUsed(input_arr, config)
            
            tc_utils.CheckServiceData(response)

            if response.Output:
                for output in response.Output:
                    # WhereUsedOutputData contains:
                    #   InputObject: The original input
                    #   Info: Array of WhereUsedParentInfo
                    input_obj = output.InputObject
                    input_uid = input_obj.Uid if input_obj else None
                    
                    if input_uid and input_uid in results:
                        parents = []
                        if output.Info:
                            for info in output.Info:
                                # WhereUsedParentInfo contains:
                                #   ParentObject: The parent ModelObject (Item or ItemRevision)
                                #   Level: The depth level
                                parent = info.ParentObject
                                if parent:
                                    parents.append(parent.Uid)
                        results[input_uid] = parents
                        
        except Exception as e:
            print(f"    Error executing batch {i}: {e}")

    return results

def load_parent_details(dm_service: DataManagementService, parent_uids: List[str], allowed_types: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """
    Loads details for the identified parent objects.

    This involves:
    1. Setting an ObjectPropertyPolicy to ensure necessary properties are loaded.
    2. Bulk loading the parent objects.
    3. Filtering them based on `allowed_types`.
    4. Resolving ItemRevisions to their parent Items (to group by Item).
    5. Loading and returning details (ID, Name, Latest Revision).

    Args:
        dm_service (DataManagementService): The Teamcenter DataManagement service instance.
        parent_uids (List[str]): List of UIDs of parent objects found by WhereUsed.
        allowed_types (Optional[List[str]]): List of strings representing Teamcenter types (e.g. "Item", "EPL Revision").
                                           If None, all types are allowed.

    Returns:
        Dict[str, Dict[str, Any]]: A dictionary mapping parent UID -> Details Dictionary.
    """
    if not parent_uids:
        return {}

    # 1. Define Policy
    # We need to handle both 'Item' and 'ItemRevision' as parents.
    # If parent is ItemRevision, we need its 'items_tag' to find the Item and then Latest Rev.
    # If parent is Item, we need 'revision_list'.
    
    # .NET Class: ObjectPropertyPolicy (Teamcenter.Soa.Common.ObjectPropertyPolicy)
    # Defines which properties to return when objects are loaded, minimizing network traffic.
    # Acts as a filter for the ServiceData return.
    policy = ObjectPropertyPolicy()
    policy.AddType("BusinessObject", Array[String](["object_name", "object_type"]))
    policy.AddType("Dataset", Array[String](["DocumentAuthor", "DocumentSubject", "DocumentTitle"]))
    policy.AddType("Item", Array[String](["item_id", "object_name", "item_master_tag", "revision_list"]))
    # Explicitly add object_name to ItemRevision as well
    policy.AddType("ItemRevision", Array[String](["item_revision_id", "object_name", "items_tag", "creation_date", "release_status_list"]))
    policy.AddType("Document", Array[String](["item_id", "object_name", "item_master_tag", "revision_list"]))
    policy.AddType("DocumentRevision", Array[String](["item_revision_id", "object_name", "items_tag", "creation_date"]))
    policy.AddType("ItemMaster", Array[String](["object_name"]))
    policy.AddType("ReleaseStatus", Array[String](["object_name"]))
    
    # Apply policy via SessionService
    conn = Session.getConnection()
    if conn:
        # .NET Call: ObjectPropertyPolicyManager.AddPolicy / SetPolicy
        policy_name = conn.ObjectPropertyPolicyManager.AddPolicy(policy, True)
        conn.ObjectPropertyPolicyManager.SetPolicy(policy_name)
        
        session_service = SessionService.getService(conn)
        if session_service:
            # .NET Call: SessionService.RefreshPOMCachePerRequest
            # Ensures we get fresh data from the server.
            session_service.RefreshPOMCachePerRequest(True)

    print(f"Loading {len(parent_uids)} unique parent objects...")
    loaded_parents = _bulk_load(dm_service, parent_uids)
    
    # Explicitly refresh parents to ensure properties like 'items_tag' are loaded
    chunk_size = 100
    if loaded_parents:
        print(f"Refreshing properties for {len(loaded_parents)} parents...")
        for i in range(0, len(loaded_parents), chunk_size):
            chunk = loaded_parents[i:i + chunk_size]
            try:
                # .NET Call: DataManagementService.RefreshObjects
                # Refreshes the objects in the client cache to ensure property values are current.
                resp = dm_service.RefreshObjects(Array[ModelObject](chunk))
                tc_utils.CheckServiceData(resp)
            except Exception as e:
                print(f"    Error refreshing parents for chunk {i}: {e}")

        # Collect and refresh ReleaseStatus objects from parents
        # This is needed if we want to check release status of parent revisions
        statuses_to_refresh = set()
        for obj in loaded_parents:
            try:
                if "ItemRevision" in obj.GetType().Name: 
                    rs_prop = obj.GetProperty("release_status_list")
                    if rs_prop and rs_prop.ModelObjectArrayValue:
                        for status in rs_prop.ModelObjectArrayValue:
                            statuses_to_refresh.add(status)
            except Exception:
                pass
        
        if statuses_to_refresh:
            status_list = list(statuses_to_refresh)
            print(f"  Refreshing {len(status_list)} ReleaseStatus objects (Parents)...")
            for i in range(0, len(status_list), chunk_size):
                chunk = status_list[i:i + chunk_size]
                try:
                    resp = dm_service.RefreshObjects(Array[ModelObject](chunk))
                    tc_utils.CheckServiceData(resp)
                except Exception as e:
                    print(f"    Error refreshing parent status chunk {i}: {e}")

    # 2. Resolve to Item UIDs
    # We need to map: Parent UID -> Item UID
    parent_to_item_uid: Dict[str, str] = {}
    item_uids_to_load: Set[str] = set()
    
    print(f"Filtering and resolving {len(loaded_parents)} parents...")
    for obj in loaded_parents:
        try:
             # Ensure the object is loaded before accessing properties
             # If the refresh above failed or was partial, we might need to reload individually or skip
             # But RefreshObjects should have handled it. 
             pass 
        except:
             continue

        # Get Displayable Type property for filtering
        obj_type_prop = ""
        try:
            # .NET Call: ModelObject.GetPropertyDisplayableValue
            obj_type_prop = obj.GetPropertyDisplayableValue("object_type")
        except:
            pass
        
        # Filter by Type if requested
        if allowed_types:
            is_allowed = False
            for t_name in allowed_types:
                # Generate candidates for type matching (Case variations, Space handling, Revision suffix)
                candidates = [
                    t_name,
                    t_name.replace(" ", ""),
                    t_name.replace(" ", "_")
                ]
                # Also check for Revision equivalents if the user provided an Item type (e.g. "EPL" -> "EPLRevision")
                candidates.append(t_name + "Revision")
                candidates.append(t_name + " Revision")
                candidates.append(t_name.replace(" ", "") + "Revision")
                candidates.append(t_name.replace(" ", "_") + "_Revision")

                for cand in candidates:
                    try:
                        # Check SOA Type (Internal Name)
                        # .NET Call: SoaType.IsInstanceOf(string typeName)
                        if obj.SoaType.IsInstanceOf(cand):
                            is_allowed = True
                            break
                        
                        # Check object_type Property (Display/Internal Name)
                        if obj_type_prop and cand.lower() == obj_type_prop.lower():
                            is_allowed = True
                            break

                    except Exception:
                        continue
                
                if is_allowed:
                    break
            
            if not is_allowed:
                continue
                
        tc_type = obj.SoaType.ClassName
        try:
            if "ItemRevision" in tc_type or obj.SoaType.IsInstanceOf("ItemRevision"):
                 # It's a revision, get the Item UID from items_tag
                 # .NET Call: ModelObject.GetProperty("items_tag")
                 items_tag_prop = obj.GetProperty("items_tag")
                 if items_tag_prop and items_tag_prop.ModelObjectValue:
                     item_uid = items_tag_prop.ModelObjectValue.Uid
                     item_uids_to_load.add(item_uid)
                     parent_to_item_uid[obj.Uid] = item_uid
            elif "Item" in tc_type or obj.SoaType.IsInstanceOf("Item"):
                # It's an Item
                item_uids_to_load.add(obj.Uid)
                parent_to_item_uid[obj.Uid] = obj.Uid
        except Exception:
            pass

    # 3. Load and Refresh target Items
    # This ensures we have fresh Item objects with loaded properties (from the policy)
    loaded_items_map: Dict[str, ModelObject] = {}
    if item_uids_to_load:
        print(f"Loading {len(item_uids_to_load)} related Item objects...")
        loaded_items_list = _bulk_load(dm_service, list(item_uids_to_load))
        
        # Refresh them
        print(f"Refreshing {len(loaded_items_list)} Item objects...")
        refresh_chunk_size = 100
        for i in range(0, len(loaded_items_list), refresh_chunk_size):
            chunk = loaded_items_list[i:i + refresh_chunk_size]
            try:
                resp = dm_service.RefreshObjects(Array[ModelObject](chunk))
                tc_utils.CheckServiceData(resp)
            except Exception as e:
                print(f"    Error refreshing items for chunk {i}: {e}")
        
        # Also refresh revisions of these items to get their details (and status)
        revisions_to_refresh = set()
        for item in loaded_items_list:
            try:
                revs_prop = item.GetProperty("revision_list")
                if revs_prop and revs_prop.ModelObjectArrayValue:
                    for rev in revs_prop.ModelObjectArrayValue:
                        revisions_to_refresh.add(rev)
            except Exception:
                pass
        
        if revisions_to_refresh:
            rev_list = list(revisions_to_refresh)
            print(f"Refreshing {len(rev_list)} Item Revisions...")
            for i in range(0, len(rev_list), refresh_chunk_size):
                chunk = rev_list[i:i + refresh_chunk_size]
                try:
                    resp = dm_service.RefreshObjects(Array[ModelObject](chunk))
                    tc_utils.CheckServiceData(resp)
                except Exception as e:
                    print(f"    Error refreshing item revisions chunk {i}: {e}")

            # And finally refresh statuses of those revisions
            item_statuses_to_refresh = set()
            for rev in rev_list:
                try:
                    rs_prop = rev.GetProperty("release_status_list")
                    if rs_prop and rs_prop.ModelObjectArrayValue:
                        for status in rs_prop.ModelObjectArrayValue:
                            item_statuses_to_refresh.add(status)
                except Exception:
                    pass
            
            if item_statuses_to_refresh:
                status_list = list(item_statuses_to_refresh)
                print(f"  Refreshing {len(status_list)} ReleaseStatus objects (Items)...")
                for i in range(0, len(status_list), refresh_chunk_size):
                    chunk = status_list[i:i + refresh_chunk_size]
                    try:
                        resp = dm_service.RefreshObjects(Array[ModelObject](chunk))
                        tc_utils.CheckServiceData(resp)
                    except Exception as e:
                        print(f"    Error refreshing item status chunk {i}: {e}")

        # Map UID -> Object
        for item in loaded_items_list:
            loaded_items_map[item.Uid] = item

    # 4. Construct the details
    details_map: Dict[str, Dict[str, Any]] = {}
    
    for parent_uid, item_uid in parent_to_item_uid.items():
        if item_uid not in loaded_items_map:
            continue
            
        item_obj = loaded_items_map[item_uid]
        
        try:
            # Ensure properties are loaded before access
            try:
                _ = item_obj.GetPropertyDisplayableValue("object_name")
                _ = item_obj.GetPropertyDisplayableValue("item_id")
            except (Exception, NetException):
                continue

            # Item Details
            item_id = item_obj.GetPropertyDisplayableValue("item_id")
            object_name = item_obj.GetPropertyDisplayableValue("object_name")
            
            # Get object type names
            internal_object_type = "N/A"
            display_object_type = "N/A"
            try:
                if item_obj.SoaType:
                    internal_object_type = item_obj.SoaType.ClassName
                elif item_obj.Type:
                    internal_object_type = item_obj.Type.Name
                
                # Retrieve the displayable value of 'object_type' property
                display_object_type = item_obj.GetPropertyDisplayableValue("object_type")
            except (Exception, NetException):
                pass
            
            # Item Master
            item_master_data = None
            try:
                # .NET Call: ModelObject.GetProperty("item_master_tag")
                im_prop = item_obj.GetProperty("item_master_tag")
                if im_prop and im_prop.ModelObjectValue:
                     im_obj = im_prop.ModelObjectValue
                     im_name = "N/A"
                     try:
                         im_name = im_obj.GetPropertyDisplayableValue("object_name")
                     except (Exception, NetException):
                         pass
                         
                     item_master_data = {
                         "uid": im_obj.Uid,
                         "object_name": im_name
                     }
            except (Exception, NetException):
                pass

            # Latest Revision
            latest_rev_data = None
            try:
                # .NET Call: ModelObject.GetProperty("revision_list")
                revs_prop = item_obj.GetProperty("revision_list")
                if revs_prop and revs_prop.ModelObjectArrayValue:
                    revs = revs_prop.ModelObjectArrayValue
                    if revs:
                        last_rev = revs[-1]
                        # Ensure properties loaded on revision
                        try:
                            rev_id = last_rev.GetPropertyDisplayableValue("item_revision_id")
                            rev_name = last_rev.GetPropertyDisplayableValue("object_name")
                            rev_date = last_rev.GetPropertyDisplayableValue("creation_date")
                            
                            latest_rev_data = {
                                "uid": last_rev.Uid,
                                "item_revision_id": rev_id,
                                "object_name": rev_name,
                                "creation_date": rev_date
                            }
                        except (Exception, NetException):
                            pass
            except (Exception, NetException):
                pass
            
            details_map[parent_uid] = {
                "item_id": item_id,
                "uid": item_uid,
                "object_name": object_name,
                "internal_object_type": internal_object_type,
                "display_object_type": display_object_type,
                "item_master": item_master_data,
                "latest_revision": latest_rev_data
            }
            
        except (Exception, NetException) as e:
            msg = str(e).split('\n')[0]
            print(f"Error processing parent {parent_uid}: {msg}")

    return details_map

def main() -> None:
    """
    Main execution entry point. 
    
    Steps:
    1. Parses arguments.
    2. Reads the input JSON file.
    3. Initializes the Teamcenter session.
    4. Loads the target objects from input UIDs.
    5. Performs the Where-Used query.
    6. Loads details for all found parents.
    7. Constructs and writes the output JSON file.
    """
    args = parse_args()
    
    # 1. Read Input
    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            input_data = json.load(f)
    except Exception as e:
        print(f"Error reading input file: {e}")
        sys.exit(1)
        
    if not isinstance(input_data, list):
        print("Error: Input JSON must be a list of objects.")
        sys.exit(1)

    # 2. Initialize Session
    session = Session(args.host)
    cred_mgr = Session.credentialManager
    if args.user:
        cred_mgr.name = args.user
    if args.password:
        cred_mgr.password = args.password
    
    group = os.getenv("TC_GROUP") or os.getenv("TCGROUP") or ""
    role = os.getenv("TC_ROLE") or os.getenv("TCROLE") or ""
    if group or role:
        cred_mgr.SetGroupRole(group, role)

    user = session.login()
    if not user:
        print("Login failed.")
        sys.exit(1)
        
    dm_service = DataManagementService.getService(Session.getConnection())

    # 3. Load Target Objects (Input Items/Revisions)
    # We map the UID from the input file to the loaded ModelObject
    target_map = load_target_objects(dm_service, input_data)
    
    if not target_map:
        print("No valid target objects found in input.")
        session.logout()
        sys.exit(0)
        
    targets = list(target_map.values())

    # 4. Perform Where Used
    # Returns { target_uid: [parent_uid, ...] }
    # Always use the new API logic
    usage_map = perform_where_used(dm_service, targets)
    
    # 5. Collect all unique parent UIDs to load
    all_parent_uids = set()
    for parents in usage_map.values():
        all_parent_uids.update(parents)
        
    # 6. Load Parent Details
    # Returns { parent_uid: { details... } }
    allowed_parent_types = None
    if args.parent_type:
        allowed_parent_types = [t.strip() for t in args.parent_type.split(',') if t.strip()]

    parent_details = load_parent_details(dm_service, list(all_parent_uids), allowed_types=allowed_parent_types)
    
    # 7. Construct Output
    output_results = []
    
    for entry in input_data:
        # Find which UID we used for this entry
        target_uid = None
        if "latest_revision" in entry and entry["latest_revision"] and "uid" in entry["latest_revision"]:
            target_uid = entry["latest_revision"]["uid"]
        elif "uid" in entry:
            target_uid = entry["uid"]
            
        if target_uid and target_uid in usage_map:
            parent_uids = usage_map[target_uid]
            
            used_in_list = []
            seen_parent_items = set() # Avoid duplicates if multiple revisions of same parent use it?
            
            for p_uid in parent_uids:
                if p_uid in parent_details:
                    p_det = parent_details[p_uid]
                    # Optional: Dedup based on Item ID if requested?
                    # "return the latest revision for each of the using object"
                    # Since we resolved to the latest revision in load_parent_details, we might have duplicates if multiple revisions of the parent used the child.
                    # But load_parent_details returns the latest revision of the parent Item.
                    # So if Parent Rev A and Parent Rev B both use Child, we get Parent Item -> Latest Rev C twice.
                    # We should dedup.
                    
                    item_id = p_det.get("item_id")
                    if item_id and item_id not in seen_parent_items:
                        used_in_list.append(p_det)
                        seen_parent_items.add(item_id)
            
            # Construct entry structure
            output_entry = {
                "input_item": entry,
                "used_in": used_in_list
            }
            output_results.append(output_entry)
        else:
            # Keep entry even if no usage found? Or if target load failed.
            output_results.append({
                "input_item": entry,
                "used_in": []
            })

    # 8. Write Output
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_results, f, indent=2)
        print(f"Successfully wrote results to {args.output}")
    except Exception as e:
        print(f"Error writing output file: {e}")

    session.logout()


if __name__ == "__main__":
    main()