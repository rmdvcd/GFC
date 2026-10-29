import 'dart:io';
import 'dart:math';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:sqlcipher_flutter_libs/sqlcipher_flutter_libs.dart';

part 'app_database.g.dart';

class Fichas extends Table {
  TextColumn get id => text()();
  TextColumn get nombre => text()();
  TextColumn get estado => text()();
  TextColumn get updatedAt => text()();
  TextColumn get documento => text()();
  @override Set<Column> get primaryKey => {id};
}
class Catalogos extends Table {
  TextColumn get id => text()();
  TextColumn get tipo => text()();
  TextColumn get documento => text()();
  @override Set<Column> get primaryKey => {id};
}

@DriftDatabase(tables: [Fichas, Catalogos])
class AppDatabase extends _$AppDatabase {
  AppDatabase(QueryExecutor e) : super(e);
  @override int get schemaVersion => 1;

  Future<List<Ficha>> listarFichas() => (select(fichas)..orderBy([(t) => OrderingTerm.desc(t.updatedAt)])).get();
  Future<void> guardarDocumento(String id, String nombre, String estado, String updatedAt, String documento) async {
    await into(fichas).insertOnConflictUpdate(FichasCompanion.insert(id: id, nombre: nombre, estado: estado, updatedAt: updatedAt, documento: documento));
  }
  Future<void> eliminarFicha(String id) => (delete(fichas)..where((t) => t.id.equals(id))).go();
  Future<Ficha?> fichaPorId(String id) => (select(fichas)..where((t) => t.id.equals(id))).getSingleOrNull();
  Future<void> guardarCatalogo(String id, String tipo, String documento) => into(catalogos).insertOnConflictUpdate(CatalogosCompanion.insert(id: id, tipo: tipo, documento: documento));
  Future<List<Catalogo>> listarCatalogo(String tipo) => (select(catalogos)..where((t) => t.tipo.equals(tipo))).get();
  Future<void> eliminarCatalogo(String id) => (delete(catalogos)..where((t) => t.id.equals(id))).go();

  /// Licensing metadata is stored in these tables inside the existing SQLCipher DB.
  Future<void> inicializarLicencias() async {
    await customStatement('CREATE TABLE IF NOT EXISTS licensing_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
    await customStatement('CREATE TABLE IF NOT EXISTS licensing_usage (license_id TEXT NOT NULL, feature TEXT NOT NULL, used_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (license_id, feature))');
    await customStatement('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)');
  }
  Future<String?> licenciaEstado(String key) async {
    final row = await customSelect('SELECT value FROM licensing_state WHERE key = ?', variables: [Variable(key)]).getSingleOrNull();
    return row?.read<String>('value');
  }
  Future<void> guardarLicenciaEstado(String key, String value) async {
    await customStatement('INSERT OR REPLACE INTO licensing_state (key, value) VALUES (?, ?)', [Variable(key), Variable(value)]);
  }
  Future<int> usoLicencia(String licenseId, String feature) async {
    final row = await customSelect('SELECT used_count FROM licensing_usage WHERE license_id = ? AND feature = ?',
      variables: [Variable(licenseId), Variable(feature)]).getSingleOrNull();
    return row?.read<int>('used_count') ?? 0;
  }
  Future<bool> consumirCuotaLicencia(String licenseId, String feature, int limite) async => transaction(() async {
    final usado = await usoLicencia(licenseId, feature);
    if (usado >= limite) return false;
    await customStatement('INSERT OR REPLACE INTO licensing_usage (license_id, feature, used_count) VALUES (?, ?, ?)', [Variable(licenseId), Variable(feature), Variable(usado + 1)]);
    await customStatement('INSERT OR REPLACE INTO licensing_state (key, value) VALUES (?, ?)', [Variable('usage_last_timestamp'), Variable(DateTime.now().toUtc().toIso8601String())]);
    return true;
  });
}

Future<AppDatabase> abrirBaseDatos() async {
  // SQLCipher is supplied by sqlcipher_flutter_libs. Create or retrieve a device-local key.
  const almacenamientoSeguro = FlutterSecureStorage();
  var clave = await almacenamientoSeguro.read(key: 'fichacosto_sqlcipher_key');
  if (clave == null) {
    final bytes = List<int>.generate(32, (_) => DateTime.now().microsecondsSinceEpoch % 256);
    // Use secure random bytes for the actual key material.
    final random = Random.secure();
    for (var i = 0; i < bytes.length; i++) { bytes[i] = random.nextInt(256); }
    clave = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    await almacenamientoSeguro.write(key: 'fichacosto_sqlcipher_key', value: clave);
  }
  await applyWorkaroundToOpenSqlCipherOnOldAndroidVersions();
  final dir = await getApplicationDocumentsDirectory();
  final archivo = File(p.join(dir.path, 'fichacosto.db'));
  final database = AppDatabase(NativeDatabase.createInBackground(archivo, setup: (db) {
    final escaped = clave!.replaceAll("'", "''");
    db.execute("PRAGMA key = '$escaped'");
  }));
  await database.inicializarLicencias();
  return database;
}
