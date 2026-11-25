import os
import shutil
import tempfile
import zipfile


class OperationsError(Exception):
    pass


def integrity_check(database_path):
    from .storage.database import DatabaseFile

    try:
        database = DatabaseFile.open(database_path)
        issues = []
        for page_id in range(database.page_count()):
            if page_id == 0:
                continue
            try:
                database.read_records(page_id)
            except Exception as exc:
                issues.append({"page_id": page_id, "error": str(exc)})
        return {"page_count": database.page_count(), "issues": issues}
    except Exception as exc:
        raise OperationsError(str(exc)) from exc


def backup_database(database_path, destination):
    database_path = os.fspath(database_path)
    destination = os.path.abspath(os.fspath(destination))
    if not os.path.isfile(database_path):
        raise OperationsError("Database file does not exist")
    os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)

    related = [
        database_path,
        os.path.splitext(database_path)[0] + ".wal",
        os.path.splitext(database_path)[0] + ".tasks.sqlite3",
    ]
    blob_directory = os.path.splitext(database_path)[0] + ".blobs"

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in related:
            if os.path.isfile(path):
                archive.write(path, os.path.basename(path))
        if os.path.isdir(blob_directory):
            for root, _, files in os.walk(blob_directory):
                for name in files:
                    path = os.path.join(root, name)
                    archive.write(
                        path,
                        os.path.relpath(path, os.path.dirname(database_path)),
                    )
    return destination


def restore_database(backup_path, destination):
    backup_path = os.path.abspath(os.fspath(backup_path))
    destination = os.path.abspath(os.fspath(destination))
    if not os.path.isfile(backup_path):
        raise OperationsError("Backup file does not exist")
    os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
    destination_directory = os.path.dirname(destination)
    destination_name = os.path.basename(destination)
    destination_stem = os.path.splitext(destination)[0]

    with tempfile.TemporaryDirectory() as extraction_directory:
        with zipfile.ZipFile(backup_path, "r") as archive:
            archive.extractall(extraction_directory)
        database_name = os.path.basename(destination)
        source_database = os.path.join(
            extraction_directory,
            destination_name,
        )
        if not os.path.isfile(source_database):
            candidates = [
                path
                for path in os.listdir(extraction_directory)
                if path.endswith(".db") or path.endswith(".tsg")
            ]
            if len(candidates) != 1:
                raise OperationsError("Backup does not contain one database file")
            source_database = os.path.join(extraction_directory, candidates[0])
        shutil.copy2(source_database, destination)

        for suffix in (".wal", ".tasks.sqlite3"):
            source = os.path.join(
                extraction_directory,
                os.path.basename(destination_stem) + suffix,
            )
            if os.path.isfile(source):
                shutil.copy2(source, destination_stem + suffix)

        source_blobs = os.path.join(
            extraction_directory,
            os.path.basename(destination_stem) + ".blobs",
        )
        if os.path.isdir(source_blobs):
            shutil.copytree(source_blobs, destination_stem + ".blobs")
    return destination
