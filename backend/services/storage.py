import os
import json
import tempfile
from config import Config
from utils.logging import _safe_log


class StorageService:
    @staticmethod
    def ensure_directories():
        os.makedirs(os.path.join(Config.STORAGE_DIR, 'projects'), exist_ok=True)
        os.makedirs(os.path.join(Config.STORAGE_DIR, 'tasks'), exist_ok=True)
        os.makedirs(os.path.join(Config.STORAGE_DIR, 'workspaces'), exist_ok=True)

    @staticmethod
    def save_json(category, filename, data):
        """Atomically save JSON data to a file.

        Writes to a temp file first, then renames to prevent partial writes
        on crash or power loss.
        """
        StorageService.ensure_directories()
        path = os.path.join(Config.STORAGE_DIR, category, filename)
        dir_name = os.path.dirname(path)

        try:
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.json.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            # Atomic rename (os.replace is atomic on POSIX, near-atomic on Windows)
            try:
                os.replace(tmp_path, path)
            except OSError:
                # Windows fallback: if target is locked, retry
                if os.path.isfile(path):
                    os.remove(path)
                os.rename(tmp_path, path)
        except Exception as e:
            # Clean up temp file on failure
            try:
                if 'tmp_path' in locals() and os.path.isfile(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            # Fall back to direct write so we don't lose data
            _safe_log(f"[Storage] Atomic save failed, falling back to direct write: {e}")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

        return path

    @staticmethod
    def load_json(category, filename):
        """Load JSON data from a file.

        Handles corrupt/empty JSON gracefully by returning None
        instead of crashing the application.
        """
        path = os.path.join(Config.STORAGE_DIR, category, filename)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content or not content.strip():
                _safe_log(f"[Storage] Empty file: {category}/{filename}")
                return None
            data = json.loads(content)
            return data
        except json.JSONDecodeError as e:
            _safe_log(f"[Storage] Corrupt JSON in {category}/{filename}: {e}")
            # Back up the corrupt file for debugging
            try:
                backup_path = path + '.corrupt'
                if not os.path.exists(backup_path):
                    os.rename(path, backup_path)
                    _safe_log(f"[Storage] Backed up corrupt file to {backup_path}")
            except OSError:
                pass
            return None
        except Exception as e:
            _safe_log(f"[Storage] Error loading {category}/{filename}: {e}")
            return None

    @staticmethod
    def list_files(category):
        StorageService.ensure_directories()
        dir_path = os.path.join(Config.STORAGE_DIR, category)
        try:
            return [f for f in os.listdir(dir_path) if f.endswith('.json')]
        except OSError:
            return []
