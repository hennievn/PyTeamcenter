#!/usr/bin/env python3
"""
Python port of Siemens Teamcenter sample "FileManagement" (.NET)

Functionality parity with the C# sample:
  • Logs into Teamcenter (username/password path for simplicity).
  • Uses the FileManagement utilities to:
      1) Upload a single local file (ReadMe.txt) into a new Text dataset.
      2) Upload MANY files: create N datasets, attach M files to each, upload
         via write tickets (PutFiles).
  • Cleans up by deleting all datasets it creates.
  • Closes the FMS/FileManagement utility object when done.

Prereqs
  • Python 3.9+
  • pythonnet → `pip install pythonnet`
  • Teamcenter SOA .NET client assemblies on disk. Set:
        TC_SOA_NET_DIR = path to netstandard2.0 DLL folder (e.g.
                          C:\\Siemens\\Teamcenter\\soa_client\\bin\\netstandard2.0)
  • Teamcenter web tier + Pool Manager running. Default host URL:
        http://localhost:7001/tc

Notes
  • This mirrors the .NET sample namespaces:
        Teamcenter.Services.Loose.Core._2006_03.FileManagement  (FileManagementUtility, GetDatasetWriteTicketsInputData, DatasetFileInfo)
        Teamcenter.Services.Strong.Core._2008_06.DataManagement (DatasetProperties2, CreateDatasets2)
  • If your environment uses SSO/TCCS, wire those in similarly to your .NET
    sample; this port sticks to user/password.
"""

import os
import sys
import argparse
import getpass
from pathlib import Path
from typing import List

# --- pythonnet bootstrap ------------------------------------------------------
try:
    import clr  # type: ignore
except Exception:
    print("pythonnet is required. Install with: pip install pythonnet")
    raise

DLL_DIR = os.environ.get("TC_SOA_NET_DIR")
if not DLL_DIR:
    print("Environment variable TC_SOA_NET_DIR is not set; cannot find Teamcenter .NET client DLLs.")
    sys.exit(2)

POSSIBLE_DLLS = [
    "TcSoaClient.dll",
    "TcSoaCommon.dll",
    "TcSoaCoreStrong.dll",
    "TcSoaStrongModel.dll",
    # Loose/Core FileManagement lives in a 'loose' assembly – try common names
    "TcSoaCoreLoose.dll",
    "TcSoaLooseCore.dll",
    # Net binding
    "TcServerNetBindingInterface.dll",
    "TcServerNetBinding.dll",
]

loaded = []
for dll in POSSIBLE_DLLS:
    p = os.path.join(DLL_DIR, dll)
    if os.path.exists(p):
        clr.AddReference(p)
        loaded.append(dll)

# --- .NET imports -------------------------------------------------------------
from System import Array, String

from Teamcenter.Soa.Client import Connection, ServiceData
from Teamcenter.Soa.Client.Model import ModelObject

from Teamcenter.Services.Strong.Core import SessionService, DataManagementService
from Teamcenter.Services.Strong.Core._2008_06.DataManagement import DatasetProperties2, CreateDatasetsResponse

from Teamcenter.Services.Loose.Core._2006_03.FileManagement import (
    FileManagementUtility,
    GetDatasetWriteTicketsInputData,
    DatasetFileInfo,
)

from Teamcenter.Schemas.Soa._2006_03.Exceptions import ServiceException, NotLoadedException

# --- Session helper (minimal, username/password) ------------------------------
class TcSession:
    def __init__(self, host: str):
        self.connection = Connection(host)
        self.session = SessionService.getService(self.connection)
        self.dm = DataManagementService.getService(self.connection)

    def login(self, user: str, password: str, group: str = "dba", role: str = "dba"):
        self.session.Login(user, password, group, role, "", "Python-FMS")

    def logout(self):
        try:
            self.session.Logout()
        except Exception:
            pass

# --- File utilities -----------------------------------------------------------
README_NAME = "ReadMe.txt"

def ensure_readme_exists(base_dir: Path) -> Path:
    """Ensure a ReadMe.txt exists (match .NET sample expectation)."""
    path = base_dir / README_NAME
    if not path.exists():
        path.write_text(
            "This is a sample file used by the FileManagement Python port of the Teamcenter sample.\n",
            encoding="utf-8",
        )
    return path

# --- Core demo mirroring the .NET sample -------------------------------------
class FileManagementDemo:
    NUMBER_OF_DATASETS = 12   # keep smaller than the C# 120 for sanity; change to 120 for 1:1
    NUMBER_OF_FILES_PER_DATASET = 3

    def __init__(self, tc: TcSession):
        self.tc = tc
        self.dm = tc.dm
        self.fm = FileManagementUtility(tc.connection)

    # ---- Single-file upload --------------------------------------------------
    def _single_ticket_input(self) -> GetDatasetWriteTicketsInputData:
        props = DatasetProperties2()
        props.ClientId = "datasetWriteTixTestClientId"
        props.Type = "Text"
        props.Name = "Sample-FMS-Upload"
        props.Description = "Testing put File"

        resp: CreateDatasetsResponse = self.dm.CreateDatasets2(Array[DatasetProperties2]([props]))
        if resp.ServiceData.sizeOfPartialErrors() > 0:
            raise ServiceException("CreateDatasets2 returned partial errors")

        dataset = resp.Output[0].Dataset

        # Ensure local file exists
        readme = ensure_readme_exists(Path.cwd())

        fi = DatasetFileInfo()
        fi.ClientId = "file_1"
        fi.FileName = str(readme)
        fi.NamedReferencedName = "Text"  # named reference
        fi.IsText = True
        fi.AllowReplace = False

        inp = GetDatasetWriteTicketsInputData()
        inp.Dataset = dataset
        inp.CreateNewVersion = False
        inp.DatasetFileInfos = Array[DatasetFileInfo]([fi])
        return inp

    def upload_single_file(self):
        inputs = Array[GetDatasetWriteTicketsInputData]([self._single_ticket_input()])
        sd: ServiceData = self.fm.PutFiles(inputs)
        if sd.sizeOfPartialErrors() > 0:
            print(f"PutFiles reported partial errors: {sd.sizeOfPartialErrors()}")
        # cleanup
        self.dm.DeleteObjects(Array[ModelObject]([inputs[0].Dataset]))

    # ---- Multiple-file upload ------------------------------------------------
    def _multi_ticket_inputs(self) -> List[GetDatasetWriteTicketsInputData]:
        count = self.NUMBER_OF_DATASETS
        props = []
        for i in range(count):
            p = DatasetProperties2()
            p.ClientId = f"datasetWriteTixTestClientId {i}"
            p.Type = "Text"
            p.Name = f"Sample-FMS-Upload-{i}"
            p.Description = "Testing Multiple put File"
            props.append(p)

        resp: CreateDatasetsResponse = self.dm.CreateDatasets2(Array[DatasetProperties2](props))
        if resp.ServiceData.sizeOfPartialErrors() > 0:
            raise ServiceException("CreateDatasets2 (multi) returned partial errors")

        inputs: List[GetDatasetWriteTicketsInputData] = []
        tmp_root = Path.cwd()
        src = ensure_readme_exists(tmp_root)

        for i in range(count):
            # Create M copies of ReadMe so each dataset gets distinct files
            file_infos = []
            for j in range(self.NUMBER_OF_FILES_PER_DATASET):
                copy_path = tmp_root / f"ReadMe_copy_{i}_{j}.txt"
                if not copy_path.exists():
                    try:
                        copy_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                    except Exception:
                        # best-effort fallback
                        copy_path.write_text("copy of ReadMe\n", encoding="utf-8")

                fi = DatasetFileInfo()
                fi.ClientId = f"file_{i}_{j}"
                fi.FileName = str(copy_path)
                fi.NamedReferencedName = "Text"
                fi.IsText = True
                fi.AllowReplace = False
                file_infos.append(fi)

            inp = GetDatasetWriteTicketsInputData()
            inp.Dataset = resp.Output[i].Dataset
            inp.CreateNewVersion = False
            inp.DatasetFileInfos = Array[DatasetFileInfo](file_infos)
            inputs.append(inp)

        return inputs

    def upload_multiple_files(self):
        inputs = Array[GetDatasetWriteTicketsInputData](self._multi_ticket_inputs())
        sd: ServiceData = self.fm.PutFiles(inputs)
        if sd.sizeOfPartialErrors() > 0:
            print(f"PutFiles (multi) reported partial errors: {sd.sizeOfPartialErrors()}")
        # cleanup – delete all created datasets
        datasets = [inp.Dataset for inp in inputs]
        self.dm.DeleteObjects(Array[ModelObject](datasets))

    def close(self):
        try:
            self.fm.Term()  # mirrors C# sample
        except Exception:
            pass

# --- CLI ----------------------------------------------------------------------

def parse_args():
    ap = argparse.ArgumentParser(description="Teamcenter FileManagement sample (Python port)")
    ap.add_argument("-host", default="http://localhost:7001/tc", help="Teamcenter server URL")
    ap.add_argument("-user", help="Username (prompt if omitted)")
    ap.add_argument("-password", help="Password (prompt if omitted)")
    ap.add_argument("-sso", default="", help="SSO URL (not implemented in this port)")
    ap.add_argument("-appID", default="", help="SSO App ID (not implemented in this port)")
    ap.add_argument("--datasets", type=int, default=12, help="Number of datasets for multi-upload (set 120 for exact parity)")
    ap.add_argument("--files-per-dataset", type=int, default=3, help="Files per dataset in multi-upload")
    return ap.parse_args()


def main():
    args = parse_args()
    user = args.user or input("User name: ")
    pwd = args.password if args.password is not None else getpass.getpass("Password: ")

    tc = TcSession(args.host)
    demo = None
    try:
        tc.login(user, pwd)
        demo = FileManagementDemo(tc)
        # Allow CLI overrides to match .NET defaults precisely if requested
        demo.NUMBER_OF_DATASETS = int(args.datasets)
        demo.NUMBER_OF_FILES_PER_DATASET = int(args.files_per_dataset)

        # 1) Single-file upload
        demo.upload_single_file()
        # 2) Multiple-file upload
        demo.upload_multiple_files()

    except ServiceException as e:
        try:
            msg = e.Message
        except Exception:
            msg = str(e)
        print("ServiceException:", msg)
    finally:
        if demo is not None:
            demo.close()
        tc.logout()


if __name__ == "__main__":
    main()
