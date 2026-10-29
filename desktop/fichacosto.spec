# Build from desktop/: python -m PyInstaller fichacosto.spec
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("sqlcipher3") + collect_submodules("flet") + ["pandas", "openpyxl", "reportlab"]
a = Analysis(
    ["run_desktop.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("../shared/ficha_costo_v1.schema.json", "shared"),
        ("../shared/licencia_v1.schema.json", "shared"),
        ("../shared/ficha148_backup_v1.schema.json", "fichacosto/backup/schemas"),
        ("../shared/ficha148_backup_payload_v1.schema.json", "fichacosto/backup/schemas"),
        ("../shared/help_content_v1.json", "fichacosto/help"),
        ("../shared/help_content_v1.schema.json", "fichacosto/help"),
        ("../assets/help/01_bienvenida.png", "fichacosto/help/assets"),
        ("../assets/help/02_entidad.png", "fichacosto/help/assets"),
        ("../assets/help/03_catalogos.png", "fichacosto/help/assets"),
        ("../assets/help/04_primera_ficha.png", "fichacosto/help/assets"),
        ("../assets/help/05_tour.png", "fichacosto/help/assets"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="FichaCosto", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=True, console=False)
