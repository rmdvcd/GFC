import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:drift/drift.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:json_schema/json_schema.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:unorm_dart/unorm_dart.dart' as unorm;

import '../data/app_database.dart';
import '../data/ficha148_validator.dart';
import '../licensing/licensing_service.dart';
import 'backup_archive.dart';
import 'backup_compression.dart';
import 'backup_crypto.dart';

const String _backupSchemaAsset = 'assets/ficha148_backup_v1.schema.json';
const String _payloadSchemaAsset = 'assets/ficha148_backup_payload_v1.schema.json';
const String _schemaVersion = '1.0.0';
const String _internalPrefix = '__fichacosto_backup_';
const String _securityPasswordKey = '${_internalPrefix}safety_password';
const String _securityPathKey = '${_internalPrefix}safety_path';
const int _minimumPasswordLength = 8;

class BackupException implements Exception {
  const BackupException(this.message);
  final String message;
  @override String toString() => message;
}

class BackupPasswordOrCorruptException extends BackupException {
  const BackupPasswordOrCorruptException()
      : super('No se pudo autenticar el respaldo: contraseña incorrecta o archivo dañado/manipulado.');
}

class BackupPreview {
  const BackupPreview({required this.manifest, required this.payload, required this.origenDiferente,
    required this.fingerprintActual});
  final Map<String, dynamic> manifest;
  final Map<String, dynamic> payload;
  final bool origenDiferente;
  final String fingerprintActual;
  int get fichas => (payload['fichas'] as List).length;
  int get insumos => (payload['insumos'] as List).length;
  int get salarios => (payload['tarifasSalarios'] as List).length;
  bool get incluyeLicencia => payload['licenciaActual'] != null;
  String get fechaCreacion => manifest['fechaCreacion'] as String;
  String get fingerprintOrigen => manifest['deviceFingerprintOrigen'] as String;
}

class ResultadoRestauracion {
  const ResultadoRestauracion({required this.modo, required this.fichas, required this.insumos,
    required this.salarios, required this.licenciaActualizada, required this.usageActualizado,
    this.respaldoSeguridad});
  final String modo;
  final int fichas, insumos, salarios;
  final bool licenciaActualizada, usageActualizado;
  final File? respaldoSeguridad;
}

String fortalezaContrasena(String password) {
  const common = {'password', 'password1', '12345678', 'qwerty123', 'letmein', 'admin123', 'fichacosto'};
  if (password.runes.length < _minimumPasswordLength || common.contains(password.toLowerCase())) return 'Débil';
  var score = min(4, password.runes.length ~/ 4);
  if (RegExp(r'[a-z]').hasMatch(password)) score++;
  if (RegExp(r'[A-Z]').hasMatch(password)) score++;
  if (RegExp(r'\d').hasMatch(password)) score++;
  if (RegExp(r'[^A-Za-z0-9]').hasMatch(password)) score++;
  score = min(4, score);
  return score < 2 ? 'Débil' : score < 4 ? 'Media' : 'Fuerte';
}

class BackupService {
  BackupService(this.database, {this.fingerprintProvider = getAndroidFingerprint,
    this.outputDirectory, this.appVersion = '0.1.0+1'});
  final AppDatabase database;
  final Future<String> Function() fingerprintProvider;
  final Directory? outputDirectory;
  final String appVersion;
  JsonSchema? _manifestSchema, _payloadSchema, _licenseSchema;

  Future<File> crearBackup(String password, {String? destino}) async {
    _validatePassword(password);
    final payload = await _snapshotPayload();
    await _validatePayload(payload);
    final salt = _secureBytes(backupSaltBytes);
    final nonce = _secureBytes(backupNonceBytes);
    final derived = await deriveBackupKey(password, salt);
    final now = _isoUtc(DateTime.now().toUtc());
    final manifest = <String, dynamic>{
      'schemaVersion': _schemaVersion, 'formato': 'ficha148_backup', 'fechaCreacion': now,
      'appOrigen': 'mobile', 'appVersion': appVersion,
      'deviceFingerprintOrigen': await fingerprintProvider(),
      'kdf': {'algoritmo': 'argon2id', 'salt': base64.encode(salt), 'memory': derived.memoryKiB,
        'iterations': backupKdfIterations, 'parallelism': backupKdfParallelism},
      'cifrado': {'algoritmo': 'AES-256-GCM', 'nonce': base64.encode(nonce)},
      'contenido': {'fichas': (payload['fichas'] as List).length, 'insumos': (payload['insumos'] as List).length,
        'salarios': (payload['tarifasSalarios'] as List).length, 'incluyeLicencia': payload['licenciaActual'] != null,
        'incluyePreferencias': true},
    };
    await _validateDocument(manifest, await _getManifestSchema(), 'El manifiesto generado no cumple el esquema.');
    final manifestBytes = _jsonBytes(manifest);
    final plaintext = _jsonBytes(payload);
    if (plaintext.length > maxBackupPlaintextBytes) throw const BackupException('El respaldo supera el tamaño máximo de contenido permitido.');
    final compressed = gzipBackup(plaintext);
    if (compressed.length + backupTagBytes > maxBackupCiphertextBytes) throw const BackupException('El respaldo supera el tamaño máximo cifrado permitido.');
    final ciphertext = await encryptBackup(derived.bytes, nonce, manifestBytes, compressed);
    final zip = buildBackupZip(manifestBytes, ciphertext);
    final directory = outputDirectory ?? await getApplicationDocumentsDirectory();
    final timestamp = now.replaceAll(RegExp(r'[:-]'), '');
    final targetPath = destino ?? p.join(directory.path, 'FichaCosto_$timestamp.ficha148.bak');
    final target = File(targetPath);
    await target.parent.create(recursive: true);
    final temp = File('${target.path}.tmp-${_secureBytes(8).map((b) => b.toRadixString(16).padLeft(2, '0')).join()}');
    try {
      await temp.writeAsBytes(zip, flush: true);
      return await temp.rename(target.path);
    } catch (_) {
      if (await temp.exists()) await temp.delete();
      rethrow;
    }
  }

  Future<BackupPreview> previsualizarBackup(File file, String password) async {
    _validatePassword(password);
    final archive = await readBackupZip(file);
    final dynamic manifestValue;
    try { manifestValue = jsonDecode(utf8.decode(archive.manifestBytes)); }
    catch (_) { throw const BackupException('El manifiesto del respaldo está dañado.'); }
    if (manifestValue is! Map<String, dynamic>) throw const BackupException('El manifiesto debe ser un objeto JSON.');
    final manifest = Map<String, dynamic>.from(manifestValue);
    await _validateDocument(manifest, await _getManifestSchema(), 'El manifiesto no cumple el formato de respaldo v1.');
    late List<int> salt, nonce;
    try {
      salt = base64.decode(manifest['kdf']['salt'] as String);
      nonce = base64.decode(manifest['cifrado']['nonce'] as String);
      if (salt.length != backupSaltBytes || nonce.length != backupNonceBytes) throw const FormatException();
    } catch (_) { throw const BackupException('Los parámetros criptográficos del manifiesto no son válidos.'); }
    final memory = manifest['kdf']['memory'] as int;
    late DerivedBackupKey key;
    try { key = await deriveBackupKey(password, salt, memoryKiB: memory, allowFallback: false); }
    catch (_) { throw const BackupException('Este dispositivo no dispone de memoria suficiente para abrir este respaldo con sus parámetros Argon2id. Libere memoria e inténtelo de nuevo; no se modificaron datos.'); }
    late Uint8List compressed;
    try {
      compressed = Uint8List.fromList(await decryptBackup(key.bytes, nonce, archive.manifestBytes, archive.ciphertext));
    } on BackupAuthenticationException {
      throw const BackupPasswordOrCorruptException();
    }
    late Uint8List plaintext;
    try { plaintext = await gunzipBackupBounded(compressed); }
    catch (_) { throw const BackupException('El flujo gzip del respaldo está dañado o supera el límite permitido.'); }
    final dynamic payloadValue;
    try { payloadValue = jsonDecode(utf8.decode(plaintext)); }
    catch (_) { throw const BackupException('El contenido autenticado no contiene JSON válido.'); }
    if (payloadValue is! Map<String, dynamic>) throw const BackupException('El contenido cifrado no es un objeto JSON.');
    final payload = Map<String, dynamic>.from(payloadValue);
    await _validatePayload(payload);
    final counts = Map<String, dynamic>.from(manifest['contenido'] as Map);
    if (counts['fichas'] != (payload['fichas'] as List).length ||
        counts['insumos'] != (payload['insumos'] as List).length ||
        counts['salarios'] != (payload['tarifasSalarios'] as List).length ||
        counts['incluyeLicencia'] != (payload['licenciaActual'] != null)) {
      throw const BackupException('Los contadores del manifiesto no coinciden con el contenido cifrado.');
    }
    final currentFingerprint = await fingerprintProvider();
    return BackupPreview(manifest: manifest, payload: payload,
      origenDiferente: currentFingerprint != manifest['deviceFingerprintOrigen'],
      fingerprintActual: currentFingerprint);
  }

  Future<ResultadoRestauracion> aplicarRestauracion(BackupPreview preview, {required String modo,
      bool restaurarLicencia = false, bool restaurarUsage = false, bool crearRespaldoSeguridad = true}) async {
    if (modo != 'reemplazar' && modo != 'fusionar') throw const BackupException('Seleccione reemplazar o fusionar.');
    await _validatePayload(preview.payload);
    File? safetyFile;
    if (modo == 'reemplazar' && crearRespaldoSeguridad) safetyFile = await _createSafetyBackup();
    final payload = preview.payload;
    final now = _isoUtc(DateTime.now().toUtc());
    try {
      await database.transaction(() async {
        if (modo == 'reemplazar') {
          await database.customStatement('DELETE FROM fichas');
          await database.customStatement('DELETE FROM catalogos');
          await _insertRecords(payload['fichas'] as List, payload['insumos'] as List, payload['tarifasSalarios'] as List);
          await database.customStatement('DELETE FROM preferences WHERE key NOT LIKE ?', [Variable('$_internalPrefix%')]);
          await _restorePreferences(Map<String, dynamic>.from(payload['preferencias'] as Map));
        } else {
          await _mergeRecords(payload['fichas'] as List, payload['insumos'] as List, payload['tarifasSalarios'] as List);
          await _restorePreferences(Map<String, dynamic>.from(payload['preferencias'] as Map));
        }
        if (restaurarLicencia) {
          final license = payload['licenciaActual'];
          if (license == null) {
            await database.customStatement('DELETE FROM licensing_state WHERE key = ?', [Variable('license_document')]);
          } else {
            await database.guardarLicenciaEstado('license_document', jsonEncode(license));
          }
        }
        if (restaurarUsage) await _restoreUsage((payload['usage']['features'] as List).cast<Map>(), payload['usage']['ultimoTimestamp'] as String?, reemplazar: modo == 'reemplazar');
        await database.guardarLicenciaEstado('last_seen_ts', now);
        await database.guardarLicenciaEstado('clock_rollback_started_at', '');
      });
    } catch (error) {
      final suffix = safetyFile == null ? '' : ' El respaldo de seguridad está en ${safetyFile.path}.';
      throw BackupException('No se aplicaron cambios; la transacción fue revertida.$suffix');
    }
    return ResultadoRestauracion(modo: modo, fichas: (payload['fichas'] as List).length,
      insumos: (payload['insumos'] as List).length, salarios: (payload['tarifasSalarios'] as List).length,
      licenciaActualizada: restaurarLicencia, usageActualizado: restaurarUsage, respaldoSeguridad: safetyFile);
  }

  Future<ResultadoRestauracion> restaurarRespaldoSeguridad() async {
    final path = await _internalPreference(_securityPathKey) as String?;
    final password = await _internalPreference(_securityPasswordKey) as String?;
    if (path == null || password == null || !await File(path).exists()) throw const BackupException('No hay un respaldo de seguridad previo disponible.');
    final preview = await previsualizarBackup(File(path), password);
    return aplicarRestauracion(preview, modo: 'reemplazar', restaurarLicencia: true,
      restaurarUsage: true, crearRespaldoSeguridad: false);
  }

  Future<Map<String, dynamic>> _snapshotPayload() async => database.transaction(() async {
    final ficheRows = await database.customSelect('SELECT documento FROM fichas').get();
    final catalogRows = await database.customSelect('SELECT tipo, documento FROM catalogos').get();
    final stateRows = await database.customSelect('SELECT key, value FROM licensing_state').get();
    final usageRows = await database.customSelect('SELECT license_id, feature, used_count FROM licensing_usage').get();
    final preferenceRows = await database.customSelect('SELECT key, value_json FROM preferences').get();
    final state = {for (final row in stateRows) row.data['key'] as String: row.data['value'] as String};
    final licenseRaw = state['license_document'];
    final license = licenseRaw == null ? null : jsonDecode(licenseRaw);
    final records = usageRows.map((row) => <String, dynamic>{
      'licenseId': row.data['license_id'], 'feature': row.data['feature'], 'usedCount': row.data['used_count'],
    }).toList();
    records.sort((a, b) => '${a['licenseId']}|${a['feature']}'.compareTo('${b['licenseId']}|${b['feature']}'));
    final preferences = <String, dynamic>{};
    for (final row in preferenceRows) {
      final key = row.data['key'] as String;
      if (!key.startsWith(_internalPrefix)) preferences[key] = jsonDecode(row.data['value_json'] as String);
    }
    final fichas = ficheRows.map((row) => jsonDecode(row.data['document'] as String)).toList();
    final insumos = catalogRows.where((row) => row.data['tipo'] == 'insumo').map((row) => jsonDecode(row.data['document'] as String)).toList();
    final salarios = catalogRows.where((row) => row.data['tipo'] == 'tarifa').map((row) => jsonDecode(row.data['document'] as String)).toList();
    final lastSeen = state['last_seen_ts'];
    return _normalizePayload({
      'schemaVersion': _schemaVersion, 'exportadoEn': _isoUtc(DateTime.now().toUtc()),
      'fichas': fichas, 'insumos': insumos, 'tarifasSalarios': salarios,
      'licenciaActual': license, 'preferencias': preferences,
      'usage': {'features': records, 'fichasCreadasTotal': records.where((r) => r['feature'] == 'fichas').fold<int>(0, (sum, r) => sum + (r['usedCount'] as int)),
        'ultimoTimestamp': state['usage_last_timestamp'] ?? lastSeen, 'lastSeenTimestamp': lastSeen},
    });
  });

  Future<void> _validatePayload(Map<String, dynamic> payload) async {
    await _validateDocument(payload, await _getPayloadSchema(), 'El contenido no cumple el esquema de respaldo v1.');
    final validator = await Ficha148Validator.desdeAssets();
    final seenFichas = <String>{};
    for (final item in payload['fichas'] as List) {
      if (item is! Map<String, dynamic>) throw const BackupException('El respaldo contiene una ficha inválida.');
      final errors = validator.validarDocumento(item);
      if (errors.isNotEmpty) throw BackupException('Ficha inválida: ${errors.take(3).join('; ')}');
      final id = (item['ficha'] as Map<String, dynamic>)['id'] as String;
      if (!seenFichas.add(id)) throw const BackupException('El respaldo contiene IDs de ficha duplicados.');
    }
    _validateUniqueIds(payload['insumos'] as List, 'insumos');
    _validateUniqueIds(payload['tarifasSalarios'] as List, 'tarifas salariales');
    final license = payload['licenciaActual'];
    if (license != null) {
      final schema = _licenseSchema ??= await _loadSchema('assets/licencia_v1.schema.json');
      await _validateDocument(Map<String, dynamic>.from(license as Map), schema, 'La copia de licencia del respaldo no cumple su esquema v1.');
    }
  }

  static void _validateUniqueIds(List records, String label) {
    final ids = <String>{};
    for (final record in records) {
      if (record is! Map || record['id'] is! String || !ids.add(record['id'] as String)) {
        throw BackupException('El respaldo contiene IDs duplicados o inválidos en $label.');
      }
    }
  }

  Future<void> _validateDocument(Map<String, dynamic> document, JsonSchema schema, String message) async {
    if (!schema.validateWithResults(document, validateFormats: true).isValid) throw BackupException(message);
  }

  Future<JsonSchema> _getManifestSchema() async => _manifestSchema ??= await _loadSchema(_backupSchemaAsset);
  Future<JsonSchema> _getPayloadSchema() async => _payloadSchema ??= await _loadSchema(_payloadSchemaAsset);
  Future<JsonSchema> _loadSchema(String asset) async {
    final value = jsonDecode(await rootBundle.loadString(asset));
    return JsonSchema.create(Map<String, dynamic>.from(value as Map), schemaVersion: SchemaVersion.draft2020_12);
  }

  Future<void> _insertRecords(List fichas, List insumos, List salarios) async {
    for (final raw in fichas) {
      final document = Map<String, dynamic>.from(raw as Map);
      final ficha = Map<String, dynamic>.from(document['ficha'] as Map);
      await database.guardarDocumento(ficha['id'] as String, ficha['nombre'] as String, ficha['estado'] as String,
        ficha['fechaActualizacion'] as String, jsonEncode(document));
    }
    for (final pair in [('insumo', insumos), ('tarifa', salarios)]) {
      for (final raw in pair.$2) {
        final record = Map<String, dynamic>.from(raw as Map);
        await database.guardarCatalogo(record['id'] as String, pair.$1, jsonEncode(record));
      }
    }
  }

  Future<void> _mergeRecords(List fichas, List insumos, List salarios) async {
    for (final raw in fichas) {
      final incoming = Map<String, dynamic>.from(raw as Map);
      final ficha = Map<String, dynamic>.from(incoming['ficha'] as Map);
      final existingRow = await database.fichaPorId(ficha['id'] as String);
      if (existingRow != null) {
        final existingDoc = Map<String, dynamic>.from(jsonDecode(existingRow.documento) as Map);
        final existingFicha = Map<String, dynamic>.from(existingDoc['ficha'] as Map);
        if (_dateCompare(existingFicha['fechaActualizacion'], ficha['fechaActualizacion']) >= 0) continue;
      }
      await database.guardarDocumento(ficha['id'] as String, ficha['nombre'] as String, ficha['estado'] as String,
        ficha['fechaActualizacion'] as String, jsonEncode(incoming));
    }
    for (final pair in [('insumo', insumos), ('tarifa', salarios)]) {
      for (final raw in pair.$2) {
        final record = Map<String, dynamic>.from(raw as Map);
        await database.guardarCatalogo(record['id'] as String, pair.$1, jsonEncode(record));
      }
    }
  }

  static int _dateCompare(dynamic left, dynamic right) {
    final a = DateTime.tryParse(left?.toString() ?? '')?.toUtc() ?? DateTime.fromMillisecondsSinceEpoch(0, isUtc: true);
    final b = DateTime.tryParse(right?.toString() ?? '')?.toUtc() ?? DateTime.fromMillisecondsSinceEpoch(0, isUtc: true);
    return a.compareTo(b);
  }

  Future<void> _restorePreferences(Map<String, dynamic> preferences) async {
    for (final entry in preferences.entries) {
      if (!entry.key.startsWith(_internalPrefix)) {
        await database.customStatement('INSERT OR REPLACE INTO preferences (key, value_json) VALUES (?, ?)',
          [Variable(entry.key), Variable(jsonEncode(entry.value))]);
      }
    }
  }

  Future<void> _restoreUsage(List<Map> records, String? lastTimestamp, {required bool reemplazar}) async {
    // Counts are monotonic on a given license ID: a stale backup cannot reset quota.
    for (final raw in records) {
      final record = Map<String, dynamic>.from(raw);
      final current = await database.usoLicencia(record['licenseId'] as String, record['feature'] as String);
      final count = max(current, record['usedCount'] as int);
      await database.customStatement('INSERT OR REPLACE INTO licensing_usage (license_id, feature, used_count) VALUES (?, ?, ?)',
        [Variable(record['licenseId']), Variable(record['feature']), Variable(count)]);
    }
    if (lastTimestamp != null) {
      final existing = await database.licenciaEstado('usage_last_timestamp');
      if (existing == null || _dateCompare(existing, lastTimestamp) < 0) {
        await database.guardarLicenciaEstado('usage_last_timestamp', lastTimestamp);
      }
    }
  }

  Future<File> _createSafetyBackup() async {
    final password = base64Url.encode(_secureBytes(32));
    final directory = Directory(p.join((await getApplicationSupportDirectory()).path, 'backups'));
    final timestamp = _isoUtc(DateTime.now().toUtc()).replaceAll(RegExp(r'[:-]'), '');
    final path = File(p.join(directory.path, '.pre-restore-$timestamp.ficha148.bak'));
    await crearBackup(password, destino: path.path);
    await database.customStatement('INSERT OR REPLACE INTO preferences (key, value_json) VALUES (?, ?)',
      [Variable(_securityPasswordKey), Variable(jsonEncode(password))]);
    await database.customStatement('INSERT OR REPLACE INTO preferences (key, value_json) VALUES (?, ?)',
      [Variable(_securityPathKey), Variable(jsonEncode(path.path))]);
    return path;
  }

  Future<dynamic> _internalPreference(String key) async {
    final row = await database.customSelect('SELECT value_json FROM preferences WHERE key = ?',
      variables: [Variable(key)]).getSingleOrNull();
    if (row == null) return null;
    return jsonDecode(row.read<String>('value_json'));
  }

  static void _validatePassword(String password) {
    if (password.runes.length < _minimumPasswordLength) throw const BackupException('La contraseña debe tener al menos 8 caracteres.');
    if (utf8.encode(password).length > 1024) throw const BackupException('La contraseña es demasiado larga.');
  }

  static List<int> _secureBytes(int length) {
    final random = Random.secure();
    return List<int>.generate(length, (_) => random.nextInt(256), growable: false);
  }

  static Uint8List _jsonBytes(dynamic value) => Uint8List.fromList(utf8.encode(jsonEncode(_normalizePayload(value))));

  static dynamic _normalizePayload(dynamic value, {String parentKey = '', bool inLicense = false}) {
    if (parentKey == 'licenciaActual') inLicense = true;
    if (value is Map) {
      final normalized = <String, dynamic>{};
      for (final entry in value.entries) {
        if (entry.key is! String) throw const BackupException('El JSON de respaldo contiene claves no textuales.');
        final key = unorm.nfc(entry.key as String);
        if (normalized.containsKey(key)) throw const BackupException('Hay claves duplicadas tras normalizar Unicode.');
        normalized[key] = _normalizePayload(entry.value, parentKey: key, inLicense: inLicense);
      }
      final keys = normalized.keys.toList()..sort();
      return <String, dynamic>{for (final key in keys) key: normalized[key]};
    }
    if (value is List) {
      final items = value.map((item) => _normalizePayload(item, parentKey: parentKey, inLicense: inLicense)).toList();
      if (items.isNotEmpty && items.every((item) => item is Map && item['id'] is String)) {
        items.sort((a, b) => (a['id'] as String).compareTo(b['id'] as String));
      }
      return items;
    }
    if (value is double) {
      if (!value.isFinite) throw const BackupException('El JSON de respaldo contiene un número no finito.');
      return value == value.truncateToDouble() ? value.toInt() : value;
    }
    if (value is String && !inLicense) {
      final normalized = unorm.nfc(value);
      const dates = {'fechaCreacion', 'fechaActualizacion', 'fechaEmision', 'fechaExpiracion', 'exportadoEn', 'ultimoTimestamp', 'lastSeenTimestamp'};
      if (dates.contains(parentKey)) {
        final parsed = DateTime.tryParse(normalized);
        if (parsed != null) return _isoUtc(parsed.toUtc());
      }
      return normalized;
    }
    return value;
  }

  static String _isoUtc(DateTime value) {
    var text = value.toUtc().toIso8601String();
    text = text.replaceFirst(RegExp(r'\.0+Z$'), 'Z');
    text = text.replaceFirst(RegExp(r'(\.\d*?)0+Z$'), r'$1Z');
    return text;
  }
}
