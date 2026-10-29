# Generador interno de licencias FichaCosto

Herramienta offline Ed25519 para personal autorizado. El archivo `.lic` contiene un payload JSON legible y una firma; la clave privada nunca debe copiarse al repositorio, a un instalador ni al dispositivo del cliente. La herramienta guarda la clave privada cifrada con contraseña (PKCS#8/BestAvailableEncryption). Guárdela en un medio interno con respaldo y acceso restringido.

Requiere Python 3.11+ y las dependencias del proyecto Desktop (`cryptography`, `jsonschema`). Ejecutar desde la raíz del repositorio:

```bash
cd desktop
python -m pip install -e .
cd ..
python tools/license_generator/cli.py --help
```

## Operaciones

1. **Crear claves una sola vez en un entorno controlado**. El destino privado predeterminado está fuera del repositorio, en `~/.config/fichacosto/license_signing_key.pem`. Se solicitan dos veces una contraseña de al menos 12 caracteres. El archivo recibe permisos de usuario cuando el sistema los admite.

```bash
python tools/license_generator/cli.py keygen \
  --private-key "$HOME/.config/fichacosto/license_signing_key.pem" \
  --public-key "$HOME/.config/fichacosto/license_public_key.b64" \
  --embed-python desktop/src/fichacosto/licensing/public_key.py \
  --embed-dart mobile/lib/licensing/license_public_key.dart
```

El paso `--embed-*` solo escribe la clave pública dentro de los clientes para verificar firmas. Revise y distribuya únicamente estos archivos públicos. **No ejecute keygen sobre una clave existente sin haber guardado antes una copia protegida**; el comando crea un nuevo par.

2. Preparar `payload.json` con `licenseId` UUID, producto `FichaCosto`, tipo, titular, `deviceFingerprint` de 64 dígitos hexadecimales, emisión/expiración ISO 8601 con zona horaria, `features` y `maxFichas`. Copie el fingerprint desde la pantalla Licencia del dispositivo. Android y Desktop producen huellas distintas; emita un archivo por dispositivo.

3. Emitir y verificar:

```bash
python tools/license_generator/cli.py issue \
  --payload payload.json \
  --private-key "$HOME/.config/fichacosto/license_signing_key.pem" \
  --output cliente.lic
python tools/license_generator/cli.py verify \
  --license cliente.lic \
  --public-key "$HOME/.config/fichacosto/license_public_key.b64"
```

`issue` pide la contraseña privada. La firma Ed25519 cubre solo `payload`, canonizado como texto Unicode NFC, objetos con claves ordenadas, JSON compacto UTF-8, sin floats/NaN. El mismo contrato se implementa en Python y Dart.

4. Revocar:

```bash
python tools/license_generator/cli.py revoke \
  --license-id "UUID-DE-LA-LICENCIA" \
  --private-key "$HOME/.config/fichacosto/license_signing_key.pem" \
  --output revocaciones.json
```

Puede pasar `--existing revocaciones.json` para sumar IDs al manifiesto anterior. El manifiesto está firmado con la misma clave. **Una revocación no llega por sí sola a equipos desconectados**; hay que distribuir/importar el manifiesto mediante un canal confiable y la aplicación debe tener soporte para cargarlo. El estado actual de la app comprueba licencias individuales; el manifiesto se puede verificar desde CLI. No presente revocación local como garantía contra dispositivos offline.

## Estados y límites de seguridad

El cliente muestra mensajes en español para firma, schema, expiración y fingerprint. La validez offline depende del reloj, archivo de base SQLCipher y binario locales. La detección de retroceso persiste `last_seen_ts` y aplica una gracia de 24 h, pero no proporciona tiempo confiable frente al propietario/admin del equipo. Una base restaurada puede recuperar estado anterior. No existe revocación inmediata offline.

No incluya claves privadas, contraseñas, `.lic` de clientes, manifiestos con datos sensibles ni archivos temporales con titulares en Git.
