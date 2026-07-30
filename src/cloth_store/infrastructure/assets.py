import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class InvalidAssetKeyError(ValueError):
    pass


class LocalAssetStorage:
    """Stores private assets beneath one configured local directory."""

    def __init__(self, base_directory: Path) -> None:
        self._base_directory = base_directory.resolve()

    def save(self, key: str, content: bytes) -> Path:
        destination = self._path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(dir=destination.parent, delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            try:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path.replace(destination)
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise

        return destination

    def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)

    def _path_for(self, key: str) -> Path:
        destination = (self._base_directory / key).resolve()
        try:
            destination.relative_to(self._base_directory)
        except ValueError as error:
            raise InvalidAssetKeyError("Asset keys cannot escape the storage directory.") from error
        return destination
