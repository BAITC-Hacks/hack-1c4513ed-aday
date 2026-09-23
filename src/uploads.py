"""Validate six uploaded workbooks before activating a supplier source."""
import hashlib
from pathlib import Path
import shutil
import tempfile
from src.loader import FILES, ROOT, load_supplier


def _remove_checked(path, root):
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Временная папка вне каталога загрузок")
    shutil.rmtree(path)


def validate_and_store(supplier, uploads):
    if supplier not in ("IEK", "SystemeElectric"):
        raise ValueError("Неизвестный поставщик")
    for name in FILES:
        if uploads.get(name) is None:
            raise ValueError(f"Не выбран файл {name}")
    payload = {name: uploads[name].getvalue() for name in FILES}
    digest = hashlib.sha256()
    for name in FILES:
        digest.update(name.encode())
        digest.update(payload[name])
    root = ROOT / "data" / "uploads" / supplier
    root.mkdir(parents=True, exist_ok=True)
    target = root / digest.hexdigest()[:16]
    staging = Path(tempfile.mkdtemp(prefix="staging-", dir=root))
    try:
        for name, content in payload.items():
            (staging / name).write_bytes(content)
        load_supplier(supplier, use_cache=False, source_dir=staging)
        if target.exists():
            _remove_checked(staging, root)
        else:
            if not target.resolve().is_relative_to(root.resolve()):
                raise ValueError("Папка назначения вне каталога загрузок")
            staging.rename(target)
        return target
    except Exception:
        if staging.exists():
            _remove_checked(staging, root)
        raise
