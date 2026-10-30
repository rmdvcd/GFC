# FichaCosto — base offline multiplataforma

MVP de dos aplicaciones hermanas para confeccionar fichas de costos y gastos, con intercambio local sin conexión mediante `.ficha148`.

## Arquitectura

- **Contrato compartido (`shared/`)**: JSON Schema 2020-12 versionado. El documento transportado es `{ "schemaVersion": 1, "ficha": {...} }`. El ZIP contiene `manifest.json` y `ficha.json`. El archivo de ejemplo está en `shared/examples/ejemplo.ficha148`.
- **Flutter (`mobile/`)**: dominio Dart, repositorio abstracto, Drift + SQLCipher con clave guardada en almacenamiento seguro del dispositivo, Riverpod y pantallas para fichas/partidas/catálogos.
- **Python (`desktop/`)**: dominio con dataclasses, repositorio SQLCipher sin fallback a SQLite plano, UI local en Flet y servicios de intercambio/exportación.
- **Monedas**: CUP y MLC se totalizan en libros separados. No hay tasa de cambio ni mezcla implícita.
- **Regulación**: los campos y fórmulas no confirmados no se presentan como exigencias de la Resolución. El margen configurable genera una estimación explícita; el coeficiente indirecto se conserva, pero no se aplica automáticamente hasta definir su base conforme a la normativa y validación del usuario.

## Contrato y paquete

`shared/ficha_costo_v1.schema.json` es la fuente canónica. Incluye UUID de ficha y partidas, fechas, estado, las cuatro categorías solicitadas, unidad/cantidad, importe y moneda, coeficientes opcionales, totales por categoría y moneda, y `extensionData` para ampliar sin inventar campos regulatorios. El ejemplo reproducible:

```bash
cd desktop
python -m venv .venv
.venv/bin/pip install -e .
PYTHONPATH=src .venv/bin/python -m fichacosto.cli crear-ejemplo ../shared/examples/ejemplo.ficha148
PYTHONPATH=src .venv/bin/python -m fichacosto.cli validar ../shared/examples/ejemplo.ficha148
```

El ZIP no se cifra: es un artefacto de transferencia que puede contener información sensible. Compártalo por un medio local seguro. La base local sí se cifra con SQLCipher. No intercambiar ni sincronizar las claves SQLCipher entre apps.

## Validación segura de `.ficha148`

La importación usa servicios desacoplados de la UI (`desktop/src/fichacosto/ficha148_validator.py` y `mobile/lib/data/ficha148_validator.dart`). Antes de importar, ambas revisan firma ZIP, nombres exactos `manifest.json` y `ficha.json`, entradas duplicadas, rutas absolutas/`..`/separadores alternativos, enlaces simbólicos y límite de 10 MB descomprimidos. Python inspecciona por streaming con `zipfile` endurecido mediante preflight; no extrae archivos a disco. Flutter usa `archive`, comprueba tamaños declarados y consume el contenido por bloques con límites. Así se evita ZipSlip y se limita el impacto de bombas de descompresión.

Después, el JSON se valida contra el esquema compartido Draft 2020-12 (`jsonschema`/`Draft202012Validator.iter_errors()` en Python y `json_schema` en Flutter). Los fallos semánticos se convierten a mensajes en español con la ruta del campo; no se muestran trazas técnicas. La interfaz lista los errores. Si la validación es correcta, muestra ficha, entidad/período disponibles y totales CUP/MLC, y solo escribe en la base cifrada después de que el usuario confirme.

```python
from fichacosto.ficha148_validator import Ficha148Validator

resumen = Ficha148Validator().validar_paquete("entrada.ficha148")
# resumen.document aún no se ha incorporado a la base: solicitar confirmación primero.
```

```dart
final resumen = await IntercambioFicha148.validarArchivo(file);
// Mostrar resumen y pedir confirmación; solo entonces llamar a repository.importar(resumen.document).
```

Los valores de entidad y período no incluidos en el contrato se presentan como `[PENDIENTE]`; no se inventan campos regulatorios.

## FichaCosto Desktop

```bash
cd desktop
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m fichacosto.app
```

La app solicita una clave SQLCipher local. Guárdela con seguridad; perderla impide descifrar la base. Para verificar operación headless (sin GUI), validar el archivo de ejemplo con `fichacosto.cli`.

Pruebas: `.venv/bin/python -m unittest discover -s tests -v`.

PDF, CSV y XLSX se exportan localmente. PyInstaller es la vía de empaquetado prevista; desde `desktop/`, instalar `.[build]` y ejecutar `python -m PyInstaller fichacosto.spec`. El spec es una base y debe probarse en cada sistema operativo destino, especialmente la inclusión de los binarios nativos de SQLCipher.

## FichaCosto Mobile

Se requiere Flutter estable y SDK Android. Desde `mobile/`:

```bash
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter run
```

Drift genera `lib/data/app_database.g.dart` mediante `build_runner`; no se versiona código generado. Se incluye el scaffold Android nativo. El esquema compartido se copia como asset en `mobile/assets/`; al cambiarlo, ejecutar `../scripts/sync_mobile_schema.sh`.

### Exportación XLSX y dependencia `archive`

El libro `.xlsx` se genera en `mobile/lib/data/xlsx_writer.dart`: una hoja (`Partidas`), textos como cadena en línea (`inlineStr`) y valores numéricos como números, empaquetados con `archive`. No se usa `package:excel` porque su última versión (4.0.6) exige `archive ^3.6.1`, incompatible con el `archive ^4.x` que necesita la lectura por bloques, con límites de tamaño, de los paquetes `.ficha148` y de los respaldos. Por eso `flutter pub upgrade --major-versions` fallaba con «version solving failed». La prueba del generador está en `mobile/test/xlsx_writer_test.dart`.

## Módulo PDF referencial

El generador Flutter está en `mobile/lib/data/ficha_costo_pdf.dart` (`FichaCostoPdf`); `printing` permite previsualizar/imprimir y `ExportacionesDocumento.pdf` guarda los bytes localmente. En la pantalla de edición se ofrecen ambas acciones. El generador Python `generar_pdf_ficha(ficha: FichaCosto) -> bytes` está expuesto en `desktop/src/fichacosto/exportaciones.py`; `exportar_pdf(ficha, destino)` lo usa desde la presentación de escritorio.

Ambos producen página A4 apaisada, márgenes de 10 mm, Helvetica, encabezados grises, tabla de seis columnas y pie con firmas. Los campos ausentes se imprimen como `[PENDIENTE]`. Los metadatos regulatorios que aún no existen en el modelo principal se leen sin alterar el contrato v1 desde `extensionData['anexoI']`:

```json
{
  "anexoI": {
    "nombreEntidad": "Nombre de entidad",
    "fechaConfeccion": "2026-10-28",
    "periodoVigencia": "2026",
    "actividadEconomica": "Actividad",
    "filas": {
      "2": [], "3": [], "6": [], "7": [], "8": []
    },
    "margenUtilidad": {
      "baseAutorizada": "Base documentada por la entidad",
      "porcentaje": 10,
      "importe": {"CUP": 5.0, "MLC": 0.0}
    },
    "firmas": {
      "elaboradoPor": {"nombre": "", "cargo": ""},
      "revisadoPor": {"nombre": "", "cargo": ""},
      "aprobadoPor": {"nombre": "", "cargo": ""}
    }
  }
}
```

Cada elemento de `filas` es una lista de conceptos con `concepto`, `unidadMedida`, `cantidad` y `precioUnitario: {"valor": número, "moneda": "CUP"|"MLC"}`. Puede incluir `importe: {"valor": número, "moneda": ...}` si el importe fuente ya está definido. Una clave de fila ausente queda pendiente; una lista vacía declara explícitamente que no hay partidas. Las filas 1, 4 y 5 pueden tomar sus partidas de las categorías existentes; `filas` las puede reemplazar cuando se necesite un desglose específico. La fila 5 imprime marcadores de desglose de depreciación/mantenimiento cuando solo existe el importe agregado.

La fila 9 se calcula solo si están confirmadas todas las filas 1–8 y no quedan otros gastos directos sin clasificar. La fila 10 requiere `baseAutorizada` e importes CUP/MLC explícitos; el porcentaje, si se informa, se muestra pero no se aplica a una base presumida. La fila 11 se calcula únicamente cuando las dos anteriores son conocidas. CUP y MLC nunca se convierten entre sí.

Ejemplos de invocación desde la presentación:

```dart
// Previsualizar/imprimir; la pantalla EditorFicha también expone esta acción.
await FichaCostoPdf(ficha: ficha).previsualizar();
// O generar y guardar bytes mediante el servicio de exportación.
final pdfFile = await ExportacionesDocumento.pdf(ficha);
```

```python
from pathlib import Path
from fichacosto.exportaciones import generar_pdf_ficha, exportar_pdf

contenido_pdf: bytes = generar_pdf_ficha(ficha)
Path("ficha.pdf").write_bytes(contenido_pdf)
# La vista de escritorio usa el mismo generador a través de:
exportar_pdf(ficha, "ficha.pdf")
```

La apariencia se mantiene equivalente entre motores PDF, aunque el salto de página puede variar ligeramente por el renderizado. Es una plantilla referencial, no certificación del Anexo I oficial: verificar estructura, conceptos, base autorizada y metodología contra el texto vigente antes de presentarla ante autoridades.

## Respaldo cifrado y restauración

El contrato compartido v1 está definido en `shared/ficha148_backup_v1.schema.json` (manifiesto visible y sin nombres/montos) y `shared/ficha148_backup_payload_v1.schema.json` (contenido cifrado). El ZIP contiene exactamente `ficha148_backup_v1/manifest.json` y `ficha148_backup_v1/payload.enc`; `meta.enc` se omite porque el payload cifrado ya contiene toda la información sensible. Los miembros ZIP se almacenan sin compresión; el JSON normalizado se comprime con gzip antes de cifrarse.

Formato interoperable: Argon2id v19 sobre UTF-8 de contraseña NFC, salt aleatorio de 16 bytes, `memory=65536 KiB`, `iterations=3`, `parallelism=4`, salida de 32 bytes; AES-256-GCM, nonce aleatorio de 12 bytes, tag de 16 bytes concatenado al ciphertext. El manifiesto compacto exacto se usa como AAD de GCM. Ante falta de memoria durante **creación** en Android, se permite 32768 KiB y ese valor queda en `manifest.kdf.memory`; al restaurar no se reduce el parámetro, porque hacerlo derivaría otra clave. El contenido JSON y sus arrays de registros con `id` se ordenan, los números integrales se normalizan a enteros, y fechas se escriben en UTC ISO-8601 `Z`. Se preserva intacta la licencia firmada para no alterar su payload. El cambio de salt/nonce hace que dos archivos no sean byte a byte iguales, pero estructura, KDF, cifrado y contrato son iguales entre plataformas.

La pantalla Respaldo permite crear el archivo `.ficha148.bak` y compartirlo/guardarlo, o seleccionar uno para verificar ZIP, manifiesto, autenticación, gzip, payload, fichas y catálogos antes de mostrar el resumen. Nada se aplica antes de confirmar. “Fusionar” inserta registros nuevos por ID y para fichas conserva la versión con `fechaActualizacion` más reciente. “Reemplazar” exige escribir `REEMPLAZAR`; antes se crea un respaldo de seguridad interno cifrado, protegido por una clave aleatoria guardada en la base SQLCipher. La aplicación usa una transacción para escribir cambios y ofrece recuperar ese respaldo si la operación falla. La licencia y el historial de uso solo se importan si el usuario activa sus casillas; la licencia guardada desde otro equipo queda como referencia y no se activa allí. El reloj anti-retroceso se reinicia a una marca local al restaurar; no se importa la hora de otro dispositivo.

La contraseña del respaldo es independiente de la clave SQLCipher y no se guarda para los respaldos del usuario. **Si se olvida, no existe recuperación del contenido**. Reemitir una licencia puede resolver una activación en otro dispositivo, pero no descifra el respaldo ni recupera sus datos. Una autenticación GCM fallida no permite distinguir matemáticamente una contraseña equivocada de un ciphertext/tag manipulado; la app comunica ambos casos en un mensaje único. ZIP/manifiesto inválidos se identifican antes de pedir la contraseña. El manifiesto en claro sí revela fingerprint de origen y contadores, de acuerdo con el contrato.

Pruebas Desktop: `.venv/bin/python -m unittest desktop.tests.test_backup_service -v`. La prueba cubre creación, lectura/descifrado y restauración sobre otra base SQLCipher. El test Flutter está en `mobile/test/backup_service_test.dart`; para ejecutarlo se requiere Flutter, no instalado en este sandbox. No se ha podido verificar aún la interoperabilidad ejecutando código Dart en este entorno.

## Onboarding y ayuda contextual offline

El contrato canónico es `shared/help_content_v1.json`, validado por `shared/help_content_v1.schema.json` (Draft 2020-12). Reúne onboarding de cinco pasos, explicaciones de entidad y filas 1–11, moneda CUP/MLC, margen, licencia y contraseña del respaldo, seis tutoriales, diez FAQ, avisos con reglas y catálogos de práctica. Los ejemplos iniciales usan importes cero y advierten que se deben sustituir por datos y comprobantes reales; no son precios oficiales. Los textos identifican explícitamente los puntos donde se debe confirmar el artículo o método exacto en la normativa vigente.

`HelpService` existe en `desktop/src/fichacosto/help/help_service.py` y `mobile/lib/help/help_service.dart`. Valida el JSON incluido, busca contenido, guarda el progreso y perfil de entidad en la base SQLCipher, registra avisos descartados y vuelve a mostrarlos después del intervalo establecido salvo que el usuario elija «No mostrar de nuevo». El icono de Ayuda abre la búsqueda de tutoriales y FAQ; las pantallas de ficha, licencia, catálogos y respaldo tienen enlaces contextuales. El onboarding se puede saltar y volver a iniciar desde Ayuda.

Las cinco ilustraciones PNG locales de `assets/help/` pesan en conjunto menos de 30 KB; se copian al paquete Desktop y a los assets Flutter mediante `scripts/sync_mobile_schema.sh`. No se usan videos ni se requiere red. Las pruebas de servicio Desktop se ejecutan con `.venv/bin/python -m unittest desktop.tests.test_help_service -v`; la prueba Flutter está en `mobile/test/help_onboarding_test.dart` y requiere Flutter/Dart.

## Licenciamiento offline v1

El contrato está en `shared/licencia_v1.schema.json` (Draft 2020-12); la firma Ed25519 cubre únicamente `payload`, canonizado como Unicode NFC, claves ordenadas, JSON compacto UTF-8 y sin valores decimales/NaN. Python y Flutter usan el mismo envelope `.lic`. El fingerprint se calcula por plataforma (Desktop: hostname/MAC/arquitectura/SO e ID estable; Android: identificadores Android/modelo/fabricante/release); por ello hay que emitir una licencia por dispositivo. Los identificadores brutos no se muestran ni se guardan.

La herramienta interna se documenta en `tools/license_generator/README.md` y ofrece `keygen`, `issue`, `verify` y `revoke`. La clave privada cifrada se almacena fuera del repositorio; la clave pública se provisiona en `desktop/src/fichacosto/licensing/public_key.py` y `mobile/lib/licensing/license_public_key.dart`. **Este checkout mantiene deliberadamente marcadores, no contiene un par de claves de producción: hasta que el responsable autorizado ejecute `keygen --embed-*` y compile/distribuya ambos clientes, estos rechazan licencias firmadas. No genere una clave privada durante un build ordinario ni la añada a Git.**

Las apps muestran estado, mensajes en español e ID copiable, importan `.lic` y guardan licencia, cuotas y `last_seen_ts` dentro de SQLCipher. La pantalla de licencia permite leer siempre los registros existentes. La creación de fichas consume cuota; PDF se permite en cualquier estado y recibe la marca diagonal «VERSIÓN NO LICENCIADA» salvo licencia activa con feature `pdf`; exportaciones avanzadas exigen `import_export`. El control local detecta retrocesos comunes del reloj y aplica gracia de 24 h. No existe reloj confiable ni revocación inmediata en equipos desconectados; restaurar la base o modificar el binario queda fuera de la garantía.

Los esquemas móviles/Desktop se sincronizan desde `shared/` con `scripts/sync_mobile_schema.sh`. Pruebas Python de licenciamiento: `.venv/bin/python -m unittest desktop.tests.test_licensing -v`. La compilación/análisis Flutter aún debe ejecutarse en un entorno con Flutter/Dart.

## Estado y límites del MVP

- CRUD de fichas, partidas e insumos/tarifas, cálculo por categoría/moneda, importación/exportación `.ficha148`, PDF/CSV/XLSX.
- La importación valida versión, manifiesto, estructura y rutas internas ZIP. La versión inicial no hace migraciones; rechaza versiones desconocidas.
- Los nombres de archivos de exportación usan la carpeta Documents o Documentos local. La aplicación no requiere red.
- No se ha certificado la exactitud jurídica ni fiscal de una plantilla de salida. Antes de uso oficial, revisar campos, metodología, coeficientes y presentación contra el texto vigente de la Resolución 148/2023 y las instrucciones aplicables.
