#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cp "$ROOT/shared/ficha_costo_v1.schema.json" "$ROOT/mobile/assets/ficha_costo_v1.schema.json"
cp "$ROOT/shared/licencia_v1.schema.json" "$ROOT/mobile/assets/licencia_v1.schema.json"
cp "$ROOT/shared/licencia_v1.schema.json" "$ROOT/desktop/src/fichacosto/licensing/licencia_v1.schema.json"
cp "$ROOT/shared/ficha148_backup_v1.schema.json" "$ROOT/mobile/assets/ficha148_backup_v1.schema.json"
cp "$ROOT/shared/ficha148_backup_payload_v1.schema.json" "$ROOT/mobile/assets/ficha148_backup_payload_v1.schema.json"
cp "$ROOT/shared/ficha148_backup_v1.schema.json" "$ROOT/desktop/src/fichacosto/backup/schemas/ficha148_backup_v1.schema.json"
cp "$ROOT/shared/ficha148_backup_payload_v1.schema.json" "$ROOT/desktop/src/fichacosto/backup/schemas/ficha148_backup_payload_v1.schema.json"
cp "$ROOT/shared/help_content_v1.schema.json" "$ROOT/mobile/assets/help_content_v1.schema.json"
cp "$ROOT/shared/help_content_v1.json" "$ROOT/mobile/assets/help_content_v1.json"
cp "$ROOT/shared/help_content_v1.schema.json" "$ROOT/desktop/src/fichacosto/help/help_content_v1.schema.json"
cp "$ROOT/shared/help_content_v1.json" "$ROOT/desktop/src/fichacosto/help/help_content_v1.json"
mkdir -p "$ROOT/mobile/assets/help" "$ROOT/desktop/src/fichacosto/help/assets"
cp "$ROOT/assets/help/"*.png "$ROOT/mobile/assets/help/"
cp "$ROOT/assets/help/"*.png "$ROOT/desktop/src/fichacosto/help/assets/"
printf '%s\n' 'Schemas, contenido y assets de ayuda sincronizados desde shared/ y assets/.'
