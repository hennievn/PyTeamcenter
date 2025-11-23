# tc_net/core.py
import os
import logging
import shutil
from typing import Iterable, List, Sequence, Tuple

from System import Array, String  # type: ignore
from System.Collections import Hashtable  # type: ignore
from Teamcenter.Soa.Client import Connection, FileManagementUtility  # type: ignore
from Teamcenter.Soa.Client.Model import ModelObject, ServiceData  # type: ignore
from Teamcenter.Soa.Common import ObjectPropertyPolicy  # type: ignore
from Teamcenter.Services.Loose.Core import FileManagementService as LooseFileManagementService  # type: ignore
from Teamcenter.Services.Strong.Core import DataManagementService, SessionService  # type: ignore
from Teamcenter.Services.Strong.Core._2007_01 import DataManagement as DM2007  # type: ignore
from Teamcenter.Services.Strong.Core._2008_06 import DataManagement as DM2008  # type: ignore
from Teamcenter.Services.Strong.Core._2009_10 import DataManagement as DM2009  # type: ignore

DATASET_RELATIONS = ("IMAN_specification", "IMAN_reference", "IMAN_manifestation", "IMAN_Rendering", "TC_Attaches")
DOCUMENT_RELATIONS = ("Fnd0IsDescribedByDocument", "IMAN_reference")
log = logging.getLogger(__name__)


def _service_data_to_error_str(sd: ServiceData | None) -> str:
    """Concatenate partial error messages from a ServiceData block."""
    if not sd or sd.sizeOfPartialErrors() == 0:
        return ""
    msgs: List[str] = []
    for i in range(sd.sizeOfPartialErrors()):
        pe = sd.GetPartialError(i)
        msgs.extend(ev.message for ev in getattr(pe, "errorValues", []))
    return "; ".join(msgs)


def connect(url, user, pwd, group="dba", role="dba", lang="en_US"):
    """Create a Teamcenter SOA connection and log in with the given credentials."""
    conn = Connection(url)
    SessionService.getService(conn).Login(user, pwd, group, role, lang)
    return conn


def set_default_policy(conn):
    """
    Register a minimal property policy so downstream helpers can resolve common attributes.

    We keep this intentionally narrow to reduce server load: item id/name, revision id/name/status,
    dataset name/type/refs, and ImanFile original names.
    """
    pol = ObjectPropertyPolicy()
    pol.AddType("Item", Array[String](["item_id", "object_name"]))
    pol.AddType("ItemRevision", Array[String](["item_revision_id", "object_name", "release_status_list"]))
    pol.AddType("Dataset", Array[String](["object_name", "object_type", "ref_list", "ref_names"]))
    pol.AddType("ImanFile", Array[String](["original_file_name"]))
    policy_manager = conn.ObjectPropertyPolicyManager
    policy_array = Array[ObjectPropertyPolicy]([pol])
    policy_ids = policy_manager.AddPolicies(policy_array)
    policy_name = policy_ids[0] if policy_ids else conn.CurrentObjectPropertyPolicy
    if policy_name:
        conn.SetObjectPropertyPolicy(policy_name)

def _default_revision_rule() -> str:
    """Return the default revision rule name, overridable via TC_REVISION_RULE env var."""
    return os.getenv("TC_REVISION_RULE", "Latest Released")  # "Released Status; Working" is used to load to trucks


def _attr_info(name: str, value: str):
    """Build a DM2008.AttrInfo tuple for Item/ItemRevision key attributes."""
    attr = DM2008.AttrInfo()
    attr.Name = name
    attr.Value = value
    return attr


def _dataset_relation_filters(relation_types: Sequence[str], dataset_types: Sequence[str] | None):
    """
    Construct DatasetRelationFilter instances for each relation/dataset_type combination.

    RelationTypeName is required; DatasetTypeName is optional to scope datasets further.
    """
    filters = []
    rel_types = list(relation_types)
    data_types = list(dataset_types or [None])
    for rel in rel_types:
        for dtype in data_types:
            rel_filter = DM2008.DatasetRelationFilter()
            rel_filter.RelationTypeName = rel
            if dtype:
                rel_filter.DatasetTypeName = dtype
            filters.append(rel_filter)
    return filters


def _build_dataset_info(item_id: str, dataset_types: Sequence[str] | None = None, named_refs: Sequence[str] | None = None):
    """
    Build a DatasetInfo that requests all datasets on the configured relations, optionally filtered.

    Args:
        item_id: Client-supplied correlation id.
        dataset_types: Optional dataset type names to include.
        named_refs: Optional named reference names to include in the response.
    """
    info = DM2008.DatasetInfo()
    info.ClientId = item_id
    dataset_filter = DM2008.DatasetFilter()
    dataset_filter.Processing = "All"
    rel_filters = _dataset_relation_filters(DATASET_RELATIONS, dataset_types)
    if rel_filters:
        dataset_filter.RelationFilters = Array[DM2008.DatasetRelationFilter](rel_filters)
    info.Filter = dataset_filter
    if named_refs:
        nr_filters = []
        for named_ref in named_refs:
            nr_filter = DM2008.NamedReferenceFilter()
            nr_filter.NamedReference = named_ref
            nr_filters.append(nr_filter)
        if nr_filters:
            info.NamedRefs = Array[DM2008.NamedReferenceFilter](nr_filters)
    return info


def _describe_item_info(item_info) -> dict:
    ids = []
    try:
        ids = [(attr.Name, attr.Value) for attr in getattr(item_info, "Ids", []) or []]
    except Exception:
        ids = ["<unavailable>"]
    return {
        "client_id": getattr(item_info, "ClientId", None),
        "use_id_first": getattr(item_info, "UseIdFirst", None),
        "uid": getattr(item_info, "Uid", None),
        "ids": ids,
    }


def _describe_rev_info(rev_info) -> dict:
    return {
        "client_id": getattr(rev_info, "ClientId", None),
        "processing": getattr(rev_info, "Processing", None),
        "rev_rule": getattr(rev_info, "RevisionRule", None),
        "nrevs": getattr(rev_info, "NRevs", None),
    }


def _describe_dataset_info(dataset_info) -> dict:
    filt = getattr(dataset_info, "Filter", None)
    rel_filters = []
    try:
        rel_filters = [
            {
                "relation": getattr(rel, "RelationTypeName", None),
                "dataset_type": getattr(rel, "DatasetTypeName", None),
            }
            for rel in (getattr(filt, "RelationFilters", None) or [])
        ]
    except Exception:
        rel_filters = ["<unavailable>"]
    return {
        "client_id": getattr(dataset_info, "ClientId", None),
        "filter": {
            "processing": getattr(filt, "Processing", None) if filt is not None else None,
            "relation_filters": rel_filters,
        },
    }


def _get_item_output_by_attribute(conn, item_id: str, nrevs: int = 1):
    """
    Call GetItemFromAttribute for the given item_id.

    Args:
        conn: Active Teamcenter connection.
        item_id: Item identifier to search for (uses ItemAttributes["item_id"]).
        nrevs: Number of revisions to return (0 = all revisions per 2009_10 docs).
    """
    dm = DataManagementService.getService(conn)

    info = DM2009.GetItemFromAttributeInfo()
    attrs = Hashtable()
    attrs["item_id"] = item_id
    info.ItemAttributes = attrs
    pref = DM2007.GetItemFromIdPref()

    resp = dm.GetItemFromAttribute(Array[DM2009.GetItemFromAttributeInfo]([info]), nrevs, pref)

    sd = getattr(resp, "ServiceData", None) or getattr(resp, "serviceData", None)
    if sd is not None and sd.sizeOfPartialErrors() > 0:
        raise RuntimeError(_service_data_to_error_str(sd))

    outputs = getattr(resp, "Output", None) or getattr(resp, "output", None)
    if not outputs:
        raise RuntimeError("No item output returned from GetItemFromAttribute.")
    return outputs[0]


def get_item_latest_with_datasets(conn, item_id, dataset_types=None, named_refs=None, latest_only: bool = True):
    """
    Fetch Item/ItemRevision + datasets using GetItemAndRelatedObjects, with a safe fallback to GetItemFromAttribute.

    Args:
        conn: Active Teamcenter connection.
        item_id: Item identifier (passed via ItemInfo.Ids when UID is unavailable).
        dataset_types: Optional dataset type names to filter.
        named_refs: Optional named reference names to include in the response.
        latest_only: If True, use revision rule to return only the latest revision; if False, return all revisions.
    """
    dms = DataManagementService.getService(conn)
    fallback_output = _get_item_output_by_attribute(conn, item_id, nrevs=1 if latest_only else 0)

    info = DM2008.GetItemAndRelatedObjectsInfo()
    info.ClientId = item_id

    item_info = DM2008.ItemInfo()
    item_info.ClientId = item_id
    item = getattr(fallback_output, "Item", None)
    item_uid = getattr(item, "Uid", None)
    if item_uid:
        item_info.Uid = item_uid
        item_info.UseIdFirst = False
    else:
        item_info.UseIdFirst = True
        item_info.Ids = Array[DM2008.AttrInfo]([_attr_info("item_id", item_id)])
    info.ItemInfo = item_info

    rev_info = DM2008.RevInfo()
    rev_info.ClientId = item_id
    if latest_only:
        rev_info.Processing = "Rule"
        rev_info.RevisionRule = _default_revision_rule()
        rev_info.NRevs = 1
    else:
        rev_info.Processing = "All"
        rev_info.NRevs = 0  # per docs: Processing=All ignores NRevs but must be set
    info.RevInfo = rev_info

    dataset_info = _build_dataset_info(item_id, dataset_types, named_refs)
    info.DatasetInfo = dataset_info

    try:
        log.debug(
            "GetItemAndRelatedObjects request for %s: %s",
            item_id,
            {
                "item_info": _describe_item_info(item_info),
                "rev_info": _describe_rev_info(rev_info),
                "dataset_info": _describe_dataset_info(dataset_info),
            },
        )
        resp = dms.GetItemAndRelatedObjects(Array[DM2008.GetItemAndRelatedObjectsInfo]([info]))

        sd = getattr(resp, "ServiceData", None) or getattr(resp, "serviceData", None)
        if sd is not None and sd.sizeOfPartialErrors() > 0:
            raise RuntimeError(_service_data_to_error_str(sd))

        outputs = getattr(resp, "Output", None) or getattr(resp, "output", None)
        if outputs:
            return outputs[0]
    except Exception as exc:
        log.error(
            "GetItemAndRelatedObjects failed for %s (payload: %s): %s",
            item_id,
            {
                "item_info": _describe_item_info(item_info),
                "rev_info": _describe_rev_info(rev_info),
                "dataset_info": _describe_dataset_info(dataset_info),
            },
            exc,
        )
        log.warning("GetItemAndRelatedObjects failed for %s, using fallback response.", item_id)

    return fallback_output


def _ensure_properties(dms, objs: Sequence[ModelObject], props: Sequence[str]):
    """Ensure the specified properties are loaded on the provided ModelObjects."""
    if not objs:
        return
    dms.GetProperties(Array[ModelObject](list(objs)), Array[String](list(props)))


def _get_display(obj: ModelObject, prop: str) -> str:
    """Fetch a displayable property value, trimmed to a plain string."""
    value = obj.GetPropertyDisplayableValue(prop)
    return (value or "").strip()


def _get_related_objects(dms, obj: ModelObject, relation: str) -> List[ModelObject]:
    """Load and return the related objects for a given GRM relation."""
    _ensure_properties(dms, [obj], [relation])
    prop = obj.GetProperty(relation)
    arr = getattr(prop, "ModelObjectArrayValue", None)
    if not arr:
        return []
    return list(arr)


def _unique_by_uid(objs: Iterable[ModelObject]) -> List[ModelObject]:
    """Deduplicate ModelObjects by Uid while preserving order."""
    unique: List[ModelObject] = []
    seen = set()
    for o in objs:
        uid = getattr(o, "Uid", None)
        if uid in seen:
            continue
        seen.add(uid)
        unique.append(o)
    return unique


def _latest_revision_for_item_id(dms, item_id: str):
    """Return the first ItemRevision for an item using GetItemFromAttribute (nrevs=1)."""
    info = DM2009.GetItemFromAttributeInfo()
    attrs = Hashtable()
    attrs["item_id"] = item_id
    info.ItemAttributes = attrs
    pref = DM2007.GetItemFromIdPref()
    resp = dms.GetItemFromAttribute(Array[DM2009.GetItemFromAttributeInfo]([info]), 1, pref)
    outputs = getattr(resp, "Output", None) or getattr(resp, "output", None)
    if not outputs:
        return None
    rev_outputs = getattr(outputs[0], "ItemRevOutput", None) or []
    if not rev_outputs:
        return None
    return getattr(rev_outputs[0], "ItemRevision", None)


def _object_types(dms, objs: Sequence[ModelObject]) -> List[str]:
    """Return lower-cased object types for a list of ModelObjects."""
    objs = list(objs)
    if not objs:
        return []
    _ensure_properties(dms, objs, ["object_type"])
    return [_get_display(o, "object_type").lower() for o in objs]


def _gather_document_revisions(
    dms, source: ModelObject, latest_only: bool = True, include_described_rel: bool = True
) -> List[ModelObject]:
    """
    Collect document revisions related to an Item/ItemRevision.

    Args:
        dms: DataManagementService instance.
        source: The Item or ItemRevision to traverse from.
        latest_only: If True, limit to the first document revision found.
        include_described_rel: Include Fnd0IsDescribedByDocument when True.
    """
    relations = list(DOCUMENT_RELATIONS)
    if not include_described_rel:
        relations = [r for r in relations if r != "Fnd0IsDescribedByDocument"]

    refs: List[ModelObject] = []
    for rel in relations:
        refs.extend(_get_related_objects(dms, source, rel))
    if not refs:
        return []
    types = _object_types(dms, refs)

    doc_revs: List[ModelObject] = []
    doc_items: List[ModelObject] = []
    for obj, typ in zip(refs, types):
        if typ.endswith("documentrevision"):
            doc_revs.append(obj)
        elif typ.endswith("document"):
            doc_items.append(obj)

    if doc_items:
        _ensure_properties(dms, doc_items, ["item_id"])
        for doc_item in doc_items:
            doc_id = _get_display(doc_item, "item_id")
            if not doc_id:
                continue
            rev = _latest_revision_for_item_id(dms, doc_id)
            if rev is not None:
                doc_revs.append(rev)

    doc_revs = _unique_by_uid(doc_revs)
    if latest_only and doc_revs:
        return doc_revs[:1]
    return doc_revs


def _filter_datasets(dms, datasets: Iterable[ModelObject], wanted=("pdf", "excel", "step")) -> List[ModelObject]:
    """Filter datasets by object_type/object_name substrings."""
    datasets = list(datasets)
    if not datasets:
        return []
    _ensure_properties(dms, datasets, ["object_type", "object_name"])
    want = {w.lower() for w in wanted}
    filtered: List[ModelObject] = []
    for ds in datasets:
        dtype = _get_display(ds, "object_type").lower()
        dname = _get_display(ds, "object_name").lower()
        if any(w in dtype for w in want) or any(w in dname for w in want):
            filtered.append(ds)
    return filtered


def _datasets_from_relations(dms, source: ModelObject, relations: Sequence[str], wanted) -> List[ModelObject]:
    """Return filtered datasets attached to a source object through the specified relations."""
    datasets: List[ModelObject] = []
    for rel in relations:
        refs = _get_related_objects(dms, source, rel)
        datasets.extend(_filter_datasets(dms, refs, wanted))
    return datasets


def _datasets_from_document(dms, doc_rev: ModelObject, wanted=("pdf", "excel", "step")) -> List[ModelObject]:
    """Convenience wrapper to pull datasets from a document revision."""
    return _datasets_from_relations(dms, doc_rev, DATASET_RELATIONS, wanted)


def get_drawing_datasets(conn, item_id: str, latest_only: bool = True, wanted=("pdf", "excel", "step")) -> Tuple[List[ModelObject], object]:
    """
    Returns drawing datasets related to the specified item along with the GetItemFromAttribute fallback output.

    Args:
        conn: Active Teamcenter connection.
        item_id: Item identifier to query.
        latest_only: Whether to restrict to the latest item revision/doc revision; False returns all revisions.
        wanted: Lower-case substrings used to filter dataset object_type/object_name.
    """
    dms = DataManagementService.getService(conn)
    item_output = get_item_latest_with_datasets(conn, item_id, latest_only=latest_only)

    item = getattr(item_output, "Item", None)
    rev_outputs = getattr(item_output, "ItemRevOutput", None) or []

    datasets: List[ModelObject] = []
    for rev_output in rev_outputs:
        item_rev = getattr(rev_output, "ItemRevision", None)
        if item_rev is None:
            continue

        datasets.extend(_datasets_from_relations(dms, item_rev, DATASET_RELATIONS, wanted))

        doc_revs = _gather_document_revisions(dms, item_rev, latest_only)
        if item is not None and not doc_revs:
            doc_revs = _gather_document_revisions(dms, item, latest_only, include_described_rel=False)

        for doc_rev in doc_revs:
            datasets.extend(_datasets_from_document(dms, doc_rev, wanted))

    datasets = _unique_by_uid(datasets)
    _ensure_properties(dms, datasets, ["object_name", "object_type"])
    return datasets, item_output


def _get_imanfiles_for_dataset(ds: ModelObject, dms: DataManagementService) -> Tuple[List[ModelObject], List[str]]:
    """Gets all ImanFile objects and their original names from a dataset."""
    prop = ds.GetProperty("ref_list")
    imans = list(getattr(prop, "ModelObjectArrayValue", []) or [])
    if not imans:
        return [], []
    _ensure_properties(dms, imans, ["original_file_name"])
    names = [(f.GetPropertyDisplayableValue("original_file_name") or f.Uid) for f in imans]
    return imans, names


def _get_unique_dst_path(directory: str, filename: str) -> str:
    """Computes a unique destination path to avoid overwriting files."""
    dst = os.path.join(directory, filename)
    if not os.path.exists(dst):
        return dst

    stem, ext = os.path.splitext(filename)
    k = 1
    while True:
        candidate = os.path.join(directory, f"{stem}_{k}{ext}")
        if not os.path.exists(candidate):
            return candidate
        k += 1


def _download_with_read_tickets(
    loose_fms,
    fmu: FileManagementUtility,
    imans: List[ModelObject],
    names: List[str],
    output_directory: str,
) -> List[str]:
    """Downloads files using FileManagementService.GetFileReadTickets (per Teamcenter Loose Core docs)."""
    if not imans:
        return []

    try:
        resp = loose_fms.GetFileReadTickets(Array[ModelObject](list(imans)))
    except Exception as exc:
        log.error("GetFileReadTickets failed: %s", exc)
        return []

    sd = getattr(resp, "ServiceData", None) or getattr(resp, "serviceData", None)
    if sd is not None and sd.sizeOfPartialErrors() > 0:
        log.warning("Partial errors requesting read tickets: %s", _service_data_to_error_str(sd))

    tickets_table = getattr(resp, "Tickets", None) or getattr(resp, "tickets", None)
    if tickets_table is None:
        log.error("FileTicketsResponse did not include a Tickets table.")
        return []

    ticket_pairs: List[Tuple[str, str]] = []
    for iman, name in zip(imans, names):
        try:
            ticket = tickets_table[iman]
        except Exception:
            ticket = None

        if not ticket:
            log.error("No ticket received for %s", name)
            continue
        ticket_pairs.append((str(ticket), name))

    if not ticket_pairs:
        return []

    ticket_array = Array[String]([ticket for ticket, _ in ticket_pairs])
    try:
        file_infos = fmu.GetFiles(ticket_array)
    except Exception as exc:
        log.error("FileManagementUtility.GetFiles(ticket[]) failed: %s", exc)
        return []

    resolved_files: List[object] = []
    if file_infos is None:
        resolved_files = []
    elif hasattr(file_infos, "Files"):
        resolved_files = list(file_infos.Files)  # type: ignore[attr-defined]
    else:
        try:
            resolved_files = list(file_infos)
        except TypeError:
            resolved_files = [file_infos]

    saved_paths: List[str] = []
    for (_, name), file_obj in zip(ticket_pairs, resolved_files):
        src_path = getattr(file_obj, "FullName", None) or str(file_obj)
        if not src_path or not os.path.exists(src_path):
            log.warning("Ticket download for %s returned invalid path: %s", name, src_path)
            continue

        dst_path = _get_unique_dst_path(output_directory, name)
        try:
            shutil.copy2(src_path, dst_path)
            saved_paths.append(dst_path)
        except Exception as exc:
            log.error("Failed to copy ticket download %s -> %s: %s", src_path, dst_path, exc)

    return saved_paths


def download_drawing_datasets(conn: Connection, datasets: List[ModelObject], output_directory: str) -> List[Tuple[str, List[str]]]:
    """
    Downloads drawing dataset files using FMU cache copies first, then loose FileManagementService tickets.
    """
    if not datasets:
        return []

    os.makedirs(output_directory, exist_ok=True)

    dms = DataManagementService.getService(conn)
    loose_fms = LooseFileManagementService.getService(conn)
    fmu = FileManagementUtility(conn)

    _ensure_properties(dms, datasets, ["object_name", "ref_list", "ref_names"])

    saved_results: List[Tuple[str, List[str]]] = []
    for ds in datasets:
        ds_name = _get_display(ds, "object_name") or ds.Uid
        imans, names = _get_imanfiles_for_dataset(ds, dms)
        if not imans:
            log.warning("Dataset %s (%s) has no ImanFile references.", ds_name, ds.Uid)
            saved_results.append((ds.Uid, []))
            continue

        saved_paths: List[str] = []
        file_map = None
        try:
            resp = fmu.GetFiles(Array[ModelObject](imans))
            file_map = getattr(resp, "FileMap", None)
        except Exception as exc:
            log.warning("FMU GetFiles failed for dataset %s: %s", ds_name, exc)

        if file_map:
            for iman, name in zip(imans, names):
                if iman not in file_map:
                    log.error("ImanFile %s not found in FMU FileMap for dataset %s.", name, ds_name)
                    continue

                src_path = file_map[iman]
                if not src_path or not os.path.exists(src_path):
                    log.warning("FMU cache path invalid for %s (%s).", name, src_path)
                    continue

                dst_path = _get_unique_dst_path(output_directory, name)
                try:
                    shutil.copy2(src_path, dst_path)
                    saved_paths.append(dst_path)
                except Exception as exc:
                    log.error("Failed to copy cache file %s -> %s: %s", src_path, dst_path, exc)

        if not saved_paths:
            saved_paths = _download_with_read_tickets(loose_fms, fmu, imans, names, output_directory)

        saved_results.append((ds.Uid, saved_paths))

    return saved_results
