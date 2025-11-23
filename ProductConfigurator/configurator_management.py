"""Utilities that mirror the Siemens ProductConfigurator VB sample."""

from __future__ import annotations

import logging

import tc_utils  # noqa: F401  # ensure assemblies are loaded

import clr  # type: ignore
import System  # type: ignore

clr.AddReference("Cfg0SoaConfiguratorStrong")  # type: ignore
clr.AddReference("Cfg0SoaStrongModelConfigurator")  # type: ignore

from System import Array, String  # type: ignore

import Teamcenter.Soa.Common as TcCommon  # type: ignore
import Teamcenter.Soa.Client.Model as TcModel  # type: ignore
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore
import Teamcenter.Soa.Exceptions as TcExceptions  # type: ignore
from Teamcenter.Services.Strong.Core import DataManagementService, SessionService  # type: ignore
from Teamcenter.Services.Strong.Core._2007_01.DataManagement import GetItemFromIdPref  # type: ignore
from Teamcenter.Services.Strong.Core._2009_10.DataManagement import (  # type: ignore
    GetItemFromAttributeInfo,
)

import Cfg0.Services.Strong.Configurator as Configurator  # type: ignore
import Cfg0.Services.Strong.Configurator._2022_06.ConfiguratorManagement as ConfigTypes  # type: ignore

LOGGER = logging.getLogger(__name__)


def initialize(session) -> None:
    """Initialize strong type factories and set an object property policy."""
    TcModel.StrongObjectFactory.Init()
    TcModel.StrongObjectFactoryCfg0configurator.Init()

    policy = TcCommon.ObjectPropertyPolicy()
    _add_to_policy(policy, "WorkspaceObject", ["object_name", "object_desc", "creation_date"])
    _add_to_policy(policy, "Item", ["item_id"])
    _add_to_policy(policy, "ItemRevision", ["item_revision_id"])
    _add_to_policy(
        policy,
        "Cfg0AbsFamily",
        ["cfg0ValueDataType", "cfg0IsMultiselect", "cfg0HasFreeFormValues"],
    )
    _add_to_policy(policy, "Cfg0AbsConfiguratorWSO", ["cfg0Sequence"])
    _add_to_policy(
        policy,
        "Cfg0ConfiguratorPerspective",
        [
            "cfg0RevisionRule",
            "cfg0VariantCriteria",
            "cfg0ProductItems",
            "cfg0Models",
            "cfg0SavedVariantRules",
            "cfg0ModelFamilies",
            "cfg0OptionFamilies",
            "cfg0OptionValues",
            "cfg0FamilyGroups",
            "cfg0ExcludeRules",
            "cfg0IncludeRules",
            "cfg0DefaultRules",
            "cfg0RuleSetCompileDate",
            "cfg0RuleSetEffectivity",
            "cfg0PrivateFamilies",
            "cfg0PrivateValues",
            "cfg0PublicFamilies",
            "cfg0PublicValues",
        ],
    )
    _add_to_policy(
        policy,
        "Cfg0ProductItem",
        ["cfg0ConfigPerspective", "cfg0PosBiasedVariantAvail", "fnd0VariantNamespace"],
    )

    session_service = SessionService.getService(session.connection)
    session_service.SetObjectPropertyPolicy(policy)


def find_item(session, item_id: str):
    """Fetch a product item by its item_id using GetItemFromAttribute."""
    dm_service = DataManagementService.getService(session.connection)

    info = GetItemFromAttributeInfo()
    info.ItemAttributes.Add("item_id", item_id)
    info.RevIds = Array[String]([""])

    response = dm_service.GetItemFromAttribute(
        Array[GetItemFromAttributeInfo]([info]), 1, GetItemFromIdPref()
    )

    service_data = getattr(response, "ServiceData", None)
    if service_data is not None and partial_error_count(service_data) > 0:
        LOGGER.warning("GetItemFromAttribute returned partial errors for item_id=%s", item_id)

    if getattr(response, "Output", None):
        output = list(response.Output)
        if output:
            item = output[0].Item
            strong_item = _to_cfg0_product_item(session, item)
            return strong_item or item
    LOGGER.error("No items returned for item_id=%s", item_id)
    return None


def get_config_perspective(item, session):
    """Return the configurator perspective related to the given product item."""
    if item is None:
        return None

    dm_service = DataManagementService.getService(session.connection)
    strong_item = _to_cfg0_product_item(session, item)
    if strong_item is not None:
        item = strong_item
        _prefetch_properties(session, item, ["cfg0ConfigPerspective"])
    else:
        _prefetch_properties(session, item, ["cfg0ConfigPerspective"])

    try:
        prop = item.GetProperty("cfg0ConfigPerspective")
    except TcExceptions.NotLoadedException:
        LOGGER.error("Property cfg0ConfigPerspective was not loaded for item %s.", item.Uid)
        return None
    except System.ArgumentException:
        manager = session.connection.ModelManager
        try:
            strong_item = manager.ConstructObject("Cfg0ProductItem", item.Uid)
            _prefetch_properties(session, strong_item, ["cfg0ConfigPerspective"])
            prop = strong_item.GetProperty("cfg0ConfigPerspective")
            item = strong_item
        except Exception as exc:
            LOGGER.error(
                "Unable to retrieve cfg0ConfigPerspective for %s as Cfg0ProductItem: %s",
                getattr(item, "Uid", "<unknown>"),
                exc,
            )
            return None
    return getattr(prop, "ModelObjectValue", None)


def get_variability(perspective, session):
    """Invoke ConfiguratorManagementService.GetVariability for the perspective."""
    if perspective is None:
        LOGGER.error("Perspective is None; cannot request variability.")
        return None

    cfg_service = Configurator.ConfiguratorManagementService.getService(session.connection)
    key_value_pairs = Array[ConfigTypes.KeyValuePair]([])
    response = cfg_service.GetVariability(perspective, key_value_pairs)
    sd = getattr(response, "ServiceData", None)
    if sd is not None and partial_error_count(sd):
        LOGGER.warning("GetVariability returned partial errors (%s).", partial_error_count(sd))
    return response


def _add_to_policy(policy, type_name: str, properties: list[str]) -> None:
    """Helper to add types and properties to the object property policy."""
    policy_type = policy.GetType(type_name)
    if policy_type is None:
        policy_type = TcCommon.PolicyType(type_name)
        policy.AddType(policy_type)

    for prop in properties:
        policy_prop = policy_type.GetProperty(prop)
        if policy_prop is None:
            policy_prop = TcCommon.PolicyProperty(prop)
            policy_prop.SetModifier(TcCommon.PolicyProperty.WITH_PROPERTIES, True)
            policy_type.AddProperty(policy_prop)


def partial_error_count(service_data) -> int:
    """Return the integer partial-error count for a ServiceData instance."""
    if service_data is None:
        return 0
    for attr in ("SizeOfPartialErrors", "sizeOfPartialErrors"):
        value = getattr(service_data, attr, None)
        if value is None:
            continue
        if callable(value):
            value = value()
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _to_cfg0_product_item(session, item):
    """Attempt to construct a strong Cfg0ProductItem via the ModelManager."""
    manager = getattr(session.connection, "ModelManager", None)
    if manager is None or item is None:
        return None
    try:
        return manager.ConstructObject("Cfg0ProductItem", item.Uid)
    except Exception as exc:
        LOGGER.debug(
            "ModelManager.ConstructObject failed for %s: %s",
            getattr(item, "Uid", "<unknown>"),
            exc,
        )
        return None


def _prefetch_properties(session, obj, prop_names: list[str]) -> None:
    """Ensure the specified properties are loaded for the given model object."""
    if obj is None or not prop_names:
        return
    try:
        dm_service = DataManagementService.getService(session.connection)
        dm_service.GetProperties(
            Array[ModelObject]([obj]),
            Array[String](prop_names),
        )
    except Exception as exc:
        LOGGER.debug(
            "Failed to prefetch properties %s for %s: %s",
            prop_names,
            getattr(obj, "Uid", "<unknown>"),
            exc,
        )
