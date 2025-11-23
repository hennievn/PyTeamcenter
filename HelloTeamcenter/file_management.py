"""Python translation of the Siemens ClientX FileManagement sample."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# Ensure Teamcenter assemblies are registered before importing .NET types.
import tc_utils  # noqa: F401  # type: ignore

import Teamcenter.Services.Loose.Core._2006_03.FileManagement as FM2006  # type: ignore
import Teamcenter.Services.Strong.Core as StrongCore  # type: ignore
import Teamcenter.Services.Strong.Core._2008_06.DataManagement as DM2008  # type: ignore
from System import Array  # type: ignore
from Teamcenter.Soa.Client import FileManagementUtility  # type: ignore
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore

LOGGER = logging.getLogger(__name__)
RESOURCE_FILE = Path(__file__).resolve().parent / "resources" / "ReadMe.txt"


@dataclass(slots=True)
class DatasetUploadSpec:
    """Captures the dataset metadata and the files staged for upload."""

    dataset: ModelObject
    files: Sequence[Path]
    file_client_ids: Sequence[str] | None = None


class FileManagementExample:
    """High-level helper that mirrors the Siemens ClientX FileManagement sample."""

    # Client IDs mirror the naming conventions used in the managed ClientX samples.
    SINGLE_CLIENT_ID = "datasetWriteTixTestClientId"
    MULTI_CLIENT_ID = "datasetWriteTixTestClientId"
    # Defaults match the C# sample (120 datasets, 3 files each); env vars allow scaling down for tests.
    MULTI_DATASET_COUNT = int(os.getenv("FMS_DATASET_COUNT", "120"))
    FILES_PER_DATASET = int(os.getenv("FMS_FILES_PER_DATASET", "3"))

    def __init__(self, connection, working_dir: Path | None = None) -> None:
        self._connection = connection
        self._working_dir = (working_dir or Path(__file__).resolve().parent / "work").resolve()
        self._working_dir.mkdir(parents=True, exist_ok=True)

        self._dm_service = StrongCore.DataManagementService.getService(connection)
        if self._dm_service is None:
            raise RuntimeError("Failed to acquire DataManagementService from the current connection.")

        self._fmu = FileManagementUtility(connection)

    # ------------------------------------------------------------------ #
    # Context manager helpers
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "FileManagementExample":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Ensure resources are freed when the example leaves a context manager."""
        self.close()

    def close(self) -> None:
        """Terminate outstanding FMS connections."""
        try:
            self._fmu.Term()
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("Failed to terminate FileManagementUtility cleanly.")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run_demo(self) -> None:
        """Execute both the single- and multi-file upload scenarios."""
        single_spec: DatasetUploadSpec | None = None
        multi_specs: list[DatasetUploadSpec] = []
        try:
            LOGGER.info("Running FileManagementUtility single-file upload example.")
            single_spec = self._prepare_single_dataset()
            self._put_files([single_spec], label="single upload")

            LOGGER.info("Running FileManagementUtility multi-file upload example.")
            multi_specs = self._prepare_multiple_datasets()
            self._put_files(multi_specs, label="multi upload")
        finally:
            datasets = []
            if single_spec is not None:
                datasets.append(single_spec.dataset)
            datasets.extend(spec.dataset for spec in multi_specs)
            self._cleanup(datasets)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _prepare_single_dataset(self) -> DatasetUploadSpec:
        """Create a dataset and stage a single file for the simple upload scenario."""
        dataset = self._create_dataset(
            client_id=self.SINGLE_CLIENT_ID,
            dataset_type="Text",
            name="Sample-FMS-Upload",
            description="Testing put File",
        )
        staged = [self._stage_example_file("ReadMe.txt")]
        return DatasetUploadSpec(dataset=dataset, files=staged, file_client_ids=("file_1",))

    def _prepare_multiple_datasets(self) -> list[DatasetUploadSpec]:
        """Create multiple datasets and stage several files for the bulk upload scenario."""
        shared_files = [
            self._stage_example_file(f"ReadMeCopy{file_index}.txt")
            for file_index in range(self.FILES_PER_DATASET)
        ]
        props: list[DM2008.DatasetProperties2] = []
        for ds_index in range(self.MULTI_DATASET_COUNT):
            prop = DM2008.DatasetProperties2()
            prop.ClientId = f"{self.MULTI_CLIENT_ID} {ds_index}"
            prop.Type = "Text"
            prop.Name = f"Sample-FMS-Upload-{ds_index}"
            prop.Description = "Testing Multiple put File"
            props.append(prop)

        datasets = self._create_datasets(props)

        specs: list[DatasetUploadSpec] = []
        for ds_index, dataset in enumerate(datasets):
            file_ids = tuple(f"Dataset {ds_index} File {file_index}" for file_index in range(self.FILES_PER_DATASET))
            specs.append(DatasetUploadSpec(dataset=dataset, files=shared_files, file_client_ids=file_ids))
        return specs

    def _create_dataset(
        self,
        *,
        client_id: str,
        dataset_type: str,
        name: str,
        description: str,
    ) -> ModelObject:
        """Create a dataset using DataManagementService.CreateDatasets2."""
        props = DM2008.DatasetProperties2()
        props.ClientId = client_id
        props.Type = dataset_type
        props.Name = name
        props.Description = description
        created = self._create_datasets([props])
        return created[0]

    def _create_datasets(self, props: Sequence[DM2008.DatasetProperties2]) -> list[ModelObject]:
        """Create multiple datasets in a single call to mirror the C# sample."""
        response = self._dm_service.CreateDatasets2(Array[DM2008.DatasetProperties2](list(props)))
        outputs = list(response.Output) if hasattr(response, "Output") else []
        if len(outputs) != len(props):
            raise RuntimeError(
                f"CreateDatasets2 returned {len(outputs)} outputs for {len(props)} requested datasets."
            )
        return [out.Dataset for out in outputs]

    def _build_ticket(self, spec: DatasetUploadSpec) -> FM2006.GetDatasetWriteTicketsInputData:
        """Build a write-ticket request for the given dataset and staged file paths."""
        file_infos = []
        for index, path in enumerate(spec.files):
            file_info = FM2006.DatasetFileInfo()
            if spec.file_client_ids and index < len(spec.file_client_ids):
                file_info.ClientId = spec.file_client_ids[index]
            else:
                file_info.ClientId = f"{spec.dataset.Uid}-file-{index}"
            file_info.FileName = str(path)
            file_info.NamedReferencedName = "Text"
            file_info.IsText = True
            file_info.AllowReplace = False
            file_infos.append(file_info)

        ticket = FM2006.GetDatasetWriteTicketsInputData()
        ticket.Dataset = spec.dataset
        ticket.CreateNewVersion = False
        ticket.DatasetFileInfos = Array[FM2006.DatasetFileInfo](file_infos)
        return ticket

    def _put_files(self, specs: Iterable[DatasetUploadSpec], label: str) -> None:
        """Upload the staged files for the provided specs via FileManagementUtility."""
        tickets: list[FM2006.GetDatasetWriteTicketsInputData] = []
        for spec in specs:
            tickets.append(self._build_ticket(spec))
        response = self._fmu.PutFiles(Array[FM2006.GetDatasetWriteTicketsInputData](tickets))
        partial_count = self._partial_error_count(response)
        if partial_count:
            LOGGER.warning("FileManagementUtility.%s reported %s partial errors.", label, partial_count)
        else:
            LOGGER.info("FileManagementUtility.%s completed without partial errors.", label)

    def _cleanup(self, datasets: Iterable[ModelObject]) -> None:
        """Delete the datasets created for the sample to keep the database clean."""
        to_delete = [ds for ds in datasets if ds is not None]
        if not to_delete:
            return
        try:
            self._dm_service.DeleteObjects(Array[ModelObject](to_delete))
        except Exception:
            LOGGER.exception("Failed to delete test datasets; manual cleanup may be required.")

    def _stage_example_file(self, filename: str, *, file_suffix: str | int | None = None) -> Path:
        """Copy the reference file into the working folder, mirroring the ClientX sample."""
        target = self._working_dir / filename
        if file_suffix is not None:
            target = self._working_dir / f"{target.stem}-{file_suffix}{target.suffix}"
        if target.exists():
            return target
        if RESOURCE_FILE.exists():
            shutil.copy2(RESOURCE_FILE, target)
        else:  # pragma: no cover - defensive fallback
            LOGGER.warning("Sample resource %s not found. Generating placeholder text.", RESOURCE_FILE)
            target.write_text("Generated placeholder content for FileManagement sample.", encoding="utf-8")
        return target

    @staticmethod
    def _partial_error_count(service_data) -> int:
        """Retrieve the partial-error count from a ServiceData response."""
        if service_data is None:
            return 0
        for attr in ("SizeOfPartialErrors", "sizeOfPartialErrors"):
            if hasattr(service_data, attr):
                getter = getattr(service_data, attr)
                return getter() if callable(getter) else int(getter)
        return 0
