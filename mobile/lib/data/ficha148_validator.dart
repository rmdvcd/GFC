import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:json_schema/json_schema.dart';

/// Límites comunes del contenedor .ficha148. Nunca se extrae contenido al sistema de archivos.
const int maxFicha148Bytes = 10 * 1024 * 1024;
const String _zipError = 'El archivo no es un paquete .ficha148 válido. Puede estar dañado o no ser un archivo ZIP.';
const Set<String> _expectedEntries = {'manifest.json', 'ficha.json'};

class Ficha148ValidationException implements Exception {
  const Ficha148ValidationException(this.messages, {this.packageError = false});
  final List<String> messages;
  final bool packageError;

  @override
  String toString() => messages.map((message) => '• $message').join('\n');
}

class Ficha148ValidationSummary {
  const Ficha148ValidationSummary({
    required this.document,
    required this.entity,
    required this.period,
    required this.cup,
    required this.mlc,
  });

  final Map<String, dynamic> document;
  final String entity;
  final String period;
  final num cup;
  final num mlc;
}

/// Validador desacoplado de UI y repositorio.
///
/// El ZIP se valida antes de leer JSON: firma, nombres exactos, entradas duplicadas,
/// enlaces simbólicos, rutas, tamaño comprimido y tamaño real descomprimido. Se lee
/// cada miembro por bloques con un límite, así un tamaño central-directory falsificado
/// no permite acumular una bomba ZIP ilimitada en memoria. No se usa extractToDisk.
class Ficha148Validator {
  Ficha148Validator._(this._schema);
  final JsonSchema _schema;

  static Future<Ficha148Validator> desdeAssets() async {
    final raw = await rootBundle.loadString('assets/ficha_costo_v1.schema.json');
    final schema = jsonDecode(raw);
    if (schema is! Map<String, dynamic>) {
      throw const FormatException('El esquema compartido no es un objeto JSON válido.');
    }
    return Ficha148Validator._(JsonSchema.create(
      schema,
      schemaVersion: SchemaVersion.draft2020_12,
    ));
  }

  /// Lee la ruta con un límite antes de cargarla completamente.
  Future<Ficha148ValidationSummary> validarArchivo(File file) async {
    try {
      if (await file.length() > maxFicha148Bytes) throw _invalidPackage();
      final bytes = await file.readAsBytes();
      return validarBytes(bytes);
    } on Ficha148ValidationException {
      rethrow;
    } on FileSystemException {
      throw _invalidPackage();
    }
  }

  /// Validación de archivo y del documento JSON; no escribe en la base de datos.
  Ficha148ValidationSummary validarBytes(Uint8List bytes) {
    if (bytes.length < 4 || bytes.length > maxFicha148Bytes ||
        bytes[0] != 0x50 || bytes[1] != 0x4b || bytes[2] != 0x03 || bytes[3] != 0x04) {
      throw _invalidPackage();
    }

    late Map<String, Uint8List> members;
    try {
      // Do not enable ZipDecoder's eager `verify` mode: it may inflate members before
      // the declared-size preflight. CRC is checked ourselves after bounded reading.
      final archive = ZipDecoder().decodeBytes(bytes);
      if (archive.files.length != _expectedEntries.length) throw _invalidPackage();
      members = <String, Uint8List>{};
      final names = <String>{};
      var declaredTotal = 0;
      for (final entry in archive.files) {
        final name = entry.name;
        _checkEntryName(name);
        if (!entry.isFile || entry.isSymbolicLink || !_expectedEntries.contains(name) || !names.add(name)) {
          throw _invalidPackage();
        }
        if (entry.size < 0 || entry.size > maxFicha148Bytes) throw _invalidPackage();
        declaredTotal += entry.size;
        if (declaredTotal > maxFicha148Bytes) throw _invalidPackage();
      }
      if (!names.containsAll(_expectedEntries) || names.length != _expectedEntries.length) {
        throw _invalidPackage();
      }
      var actualTotal = 0;
      for (final entry in archive.files) {
        final data = _readBounded(entry, maxFicha148Bytes - actualTotal);
        actualTotal += data.length;
        if (actualTotal > maxFicha148Bytes || data.length != entry.size ||
            (entry.crc32 != null && getCrc32(data) != entry.crc32)) {
          throw _invalidPackage();
        }
        members[entry.name] = data;
      }
    } on Ficha148ValidationException {
      rethrow;
    } catch (_) {
      // Decoder exceptions are intentionally hidden from the UI; never show a stack trace.
      throw _invalidPackage();
    }

    late dynamic manifestValue;
    late dynamic documentValue;
    try {
      manifestValue = jsonDecode(utf8.decode(members['manifest.json']!));
    } on FormatException {
      throw const Ficha148ValidationException(['El archivo manifest.json contiene JSON mal formado.']);
    }
    try {
      documentValue = jsonDecode(utf8.decode(members['ficha.json']!));
    } on FormatException {
      throw const Ficha148ValidationException(['El archivo ficha.json contiene JSON mal formado.']);
    }
    if (manifestValue is! Map<String, dynamic>) throw _invalidPackage();
    if (documentValue is! Map<String, dynamic>) {
      throw const Ficha148ValidationException(['El contenido de ficha.json debe ser un objeto JSON.']);
    }
    if (manifestValue['format'] != 'ficha148' || manifestValue['formatVersion'] is! int || manifestValue['formatVersion'] != 1 ||
        manifestValue['document'] != 'ficha.json' || manifestValue['schemaVersion'] is! int ||
        documentValue['schemaVersion'] is! int || manifestValue['schemaVersion'] != documentValue['schemaVersion']) {
      throw _invalidPackage();
    }

    validarDocumento(documentValue);
    final ficha = documentValue['ficha'] as Map<String, dynamic>;
    final totales = ficha['totales'] as Map<String, dynamic>;
    final costoTotal = totales['costoTotal'] as Map<String, dynamic>;
    final extension = ficha['extensionData'] is Map ? ficha['extensionData'] as Map : const <String, dynamic>{};
    final anexo = extension['anexoI'] is Map ? extension['anexoI'] as Map : const <String, dynamic>{};
    return Ficha148ValidationSummary(
      document: documentValue,
      entity: _optionalString(anexo['nombreEntidad']),
      period: _optionalString(anexo['periodoVigencia']),
      cup: costoTotal['CUP'] as num,
      mlc: costoTotal['MLC'] as num,
    );
  }

  /// Devuelve todos los errores del contrato compartido en lenguaje de usuario.
  List<String> validarDocumento(dynamic document) {
    if (document is! Map<String, dynamic>) return const ['El contenido de ficha.json debe ser un objeto JSON.'];
    final results = _schema.validateWithResults(document, validateFormats: true);
    final messages = <String>[];
    if (!results.isValid) {
      for (final error in results.errors) {
        // The schema's only format keywords are UUID and date-time; these are
        // checked below with stricter, cross-platform wording.
        if (!error.schemaPath.toLowerCase().contains('/format')) {
          messages.addAll(_translateError(error));
        }
        if (messages.length >= 50) break;
      }
    }
    messages.addAll(_validateFormats(document));
    final unique = messages.toSet().toList();
    if (unique.length > 50) {
      return [...unique.take(50), 'Hay más errores; corrija los anteriores y vuelva a validar.'];
    }
    return unique;
  }

  void validarDocumentoOExcepcion(dynamic document) {
    final errors = validarDocumento(document);
    if (errors.isNotEmpty) throw Ficha148ValidationException(errors);
  }

  // Enforce the schema's `format` keywords explicitly as well as through the
  // validator package; this keeps UUID/date-time behavior aligned with Python's FormatChecker.
  static List<String> _validateFormats(Map<String, dynamic> document) {
    final errors = <String>[];
    final ficha = document['ficha'];
    if (ficha is! Map) return errors;
    void checkUuid(dynamic value, String path, {bool nullable = false}) {
      if (value == null && nullable) return;
      if (value is String && !RegExp(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$').hasMatch(value)) {
        errors.add('El campo $path debe tener un UUID válido.');
      }
    }
    void checkDate(dynamic value, String path) {
      if (value is! String) return;
      final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|([+-])(\d{2}):(\d{2}))$').firstMatch(value);
      if (match == null || DateTime.tryParse(value) == null) {
        errors.add('El campo $path debe tener una fecha y hora ISO 8601 válida.');
        return;
      }
      final year = int.parse(match.group(1)!);
      final month = int.parse(match.group(2)!);
      final day = int.parse(match.group(3)!);
      final hour = int.parse(match.group(4)!);
      final minute = int.parse(match.group(5)!);
      final second = int.parse(match.group(6)!);
      final offsetHour = int.tryParse(match.group(9) ?? '0') ?? 0;
      final offsetMinute = int.tryParse(match.group(10) ?? '0') ?? 0;
      final normalized = DateTime.utc(year, month, day);
      if (year < 1 || normalized.year != year || normalized.month != month || normalized.day != day ||
          hour > 23 || minute > 59 || second > 59 || offsetHour > 23 || offsetMinute > 59) {
        errors.add('El campo $path debe tener una fecha y hora ISO 8601 válida.');
      }
    }
    checkUuid(ficha['id'], 'ficha › identificador UUID');
    checkDate(ficha['fechaCreacion'], 'ficha › fecha de creación');
    checkDate(ficha['fechaActualizacion'], 'ficha › fecha de actualización');
    final partidas = ficha['partidas'];
    if (partidas is List) {
      for (var i = 0; i < partidas.length; i++) {
        final partida = partidas[i];
        if (partida is Map) {
          checkUuid(partida['id'], 'partida ${i + 1} › identificador UUID');
          checkUuid(partida['insumoId'], 'partida ${i + 1} › identificador del insumo', nullable: true);
        }
      }
    }
    final snapshot = ficha['catalogosSnapshot'];
    if (snapshot is Map) {
      for (final key in ['insumos', 'tarifasSalario']) {
        final records = snapshot[key];
        if (records is List) {
          for (var i = 0; i < records.length; i++) {
            final record = records[i];
            if (record is Map) checkUuid(record['id'], '${_label(key)} ${i + 1} › identificador UUID');
          }
        }
      }
    }
    return errors;
  }

  static Uint8List _readBounded(ArchiveFile entry, int remaining) {
    if (remaining < 0 || entry.size > remaining) throw _invalidPackage();
    final stream = entry.getContent();
    if (stream == null) throw _invalidPackage();
    final builder = BytesBuilder(copy: false);
    var actual = 0;
    while (!stream.isEOS) {
      final count = stream.length < 64 * 1024 ? stream.length : 64 * 1024;
      if (count <= 0) throw _invalidPackage();
      final chunk = stream.readBytes(count).toUint8List();
      actual += chunk.length;
      if (actual > remaining || actual > maxFicha148Bytes || chunk.isEmpty) throw _invalidPackage();
      builder.add(chunk);
    }
    return builder.takeBytes();
  }

  static void _checkEntryName(String name) {
    final components = name.split('/');
    if (name.isEmpty || name.startsWith('/') || name.contains('\\') || name.contains(':') ||
        components.any((component) => component.isEmpty || component == '.' || component == '..')) {
      throw _invalidPackage();
    }
  }

  static Ficha148ValidationException _invalidPackage() =>
      const Ficha148ValidationException([_zipError], packageError: true);

  static String _optionalString(dynamic value) => value is String && value.trim().isNotEmpty ? value.trim() : '[PENDIENTE]';

  static List<String> _translateError(ValidationError error) {
    final path = error.instancePath;
    final readablePath = _humanPath(path);
    final technical = error.message.toLowerCase();
    final schemaPath = error.schemaPath.toLowerCase();

    if (technical.contains('required') || technical.contains('missing')) {
      final missing = RegExp(r'required\s+(?:prop|property)\s+missing\s*:\s*([a-zA-Z0-9_]+)', caseSensitive: false).firstMatch(error.message)?.group(1)
          ?? RegExp(r'missing\s+required\s+property\s*:?\s*([a-zA-Z0-9_]+)', caseSensitive: false).firstMatch(error.message)?.group(1)
          ?? RegExp(r'required\s+property\s+([a-zA-Z0-9_]+)', caseSensitive: false).firstMatch(error.message)?.group(1);
      if (missing != null) return ['Falta el campo obligatorio: ${_label(missing)}.'];
      return ['Falta un campo obligatorio en $readablePath.'];
    }
    if (technical.contains('additional propert') || technical.contains('unexpected propert')) {
      return ['El campo $readablePath contiene una propiedad no reconocida.'];
    }
    if (schemaPath.contains('/format') || technical.contains('format')) {
      final kind = schemaPath.contains('uuid') || technical.contains('uuid') ? 'un UUID válido' : 'un formato válido';
      return ['El campo $readablePath debe tener $kind.'];
    }
    if (schemaPath.contains('/type') || technical.contains('type')) {
      return ['El campo $readablePath tiene un tipo de dato incompatible con el esquema.'];
    }
    if (schemaPath.contains('/enum') || schemaPath.contains('/const') || technical.contains('enum') || technical.contains('const')) {
      return ['El campo $readablePath tiene un valor no permitido.'];
    }
    if (schemaPath.contains('/minlength') || technical.contains('minlength') || technical.contains('minimum length')) {
      return ['El campo $readablePath no puede estar vacío.'];
    }
    if (technical.contains('minimum') || schemaPath.contains('/minimum')) {
      return ['El campo $readablePath no puede ser menor que el mínimo permitido.'];
    }
    if (technical.contains('pattern') || schemaPath.contains('/pattern')) {
      return ['El campo $readablePath no cumple el formato esperado.'];
    }
    // Generic user-facing fallback. Never expose raw library diagnostics or a trace.
    return ['El campo $readablePath no cumple una regla obligatoria del formato ficha148.'];
  }

  static String _humanPath(String pointer) {
    if (pointer.isEmpty || pointer == '/') return 'el documento';
    final parts = pointer.split('/').skip(1).map((part) => part.replaceAll('~1', '/').replaceAll('~0', '~')).toList();
    final labels = <String>[];
    for (final part in parts) {
      final index = int.tryParse(part);
      if (index != null) {
        labels.add('partida ${index + 1}');
      } else {
        labels.add(_label(part));
      }
    }
    return labels.join(' › ');
  }

  static String _label(String key) => const {
    'schemaVersion': 'versión del esquema', 'ficha': 'ficha', 'id': 'identificador UUID',
    'nombre': 'nombre de la ficha', 'descripcion': 'descripción', 'fechaCreacion': 'fecha de creación',
    'fechaActualizacion': 'fecha de actualización', 'estado': 'estado', 'monedaBase': 'moneda base',
    'partidas': 'partidas', 'categoria': 'categoría', 'cantidad': 'cantidad', 'unidadMedida': 'unidad de medida',
    'costoUnitario': 'costo unitario', 'subtotal': 'subtotal', 'valor': 'valor', 'moneda': 'moneda',
    'catalogosSnapshot': 'instantánea de catálogos', 'insumos': 'insumos', 'tarifasSalario': 'tarifas salariales',
    'cargo': 'cargo', 'tarifa': 'tarifa', 'unidadTarifa': 'unidad de tarifa', 'coeficientes': 'coeficientes',
    'coeficienteIndirecto': 'coeficiente indirecto', 'margenGanancia': 'margen de ganancia',
    'unidadCoeficiente': 'unidad del coeficiente', 'totales': 'totales', 'porCategoria': 'totales por categoría',
    'costoTotal': 'costo total', 'CUP': 'CUP', 'MLC': 'MLC', 'precioCalculado': 'precio calculado',
    'extensionData': 'datos adicionales',
  }[key] ?? key;
}
