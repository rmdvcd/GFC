# Ejemplo `.ficha148`

Un `.ficha148` es un ZIP sin contraseña (la confidencialidad local corresponde a la base de datos cifrada, no al intercambio) con:

```text
manifest.json
ficha.json
```

`ficha.json` cumple `../ficha_costo_v1.schema.json`. El manifiesto identifica el formato y el nombre del documento. El archivo de ejemplo binario se puede regenerar desde la raíz del repo con:

```bash
PYTHONPATH=desktop python -m fichacosto.cli crear-ejemplo shared/examples/ejemplo.ficha148
```

El importador debe validar la ruta interna y tamaño del ZIP antes de leerlo y verificar `schemaVersion` antes de persistir.
