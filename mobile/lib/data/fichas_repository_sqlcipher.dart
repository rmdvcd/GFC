import 'dart:convert';
import '../domain/models.dart';
import '../domain/repositories.dart';
import 'app_database.dart';
import 'ficha148_validator.dart';

class FichasRepositorySqlCipher implements FichasRepository, CatalogosRepository {
  FichasRepositorySqlCipher(this.db);
  final AppDatabase db;

  @override
  Future<List<FichaCosto>> listar() async => (await db.listarFichas())
      .map((row) => FichaCosto.fromDocument(jsonDecode(row.documento) as Map<String, dynamic>)).toList();

  @override
  Future<void> guardar(FichaCosto ficha) async {
    final doc = ficha.toDocument();
    final f = doc['ficha'] as Map<String, dynamic>;
    await db.guardarDocumento(f['id'], f['nombre'], f['estado'], f['fechaActualizacion'], jsonEncode(doc));
  }

  @override
  Future<void> eliminar(String id) => db.eliminarFicha(id);

  @override
  Future<void> importar(Map<String, dynamic> documento) async {
    final validator = await Ficha148Validator.desdeAssets();
    validator.validarDocumentoOExcepcion(documento);
    final f = Map<String, dynamic>.from(documento['ficha']);
    await db.guardarDocumento(f['id'], f['nombre'], f['estado'], f['fechaActualizacion'], jsonEncode(documento));
  }

  @override
  Future<Map<String, dynamic>> exportar(String id) async {
    final row = await db.fichaPorId(id);
    if (row == null) throw StateError('No se encontró la ficha');
    final doc = jsonDecode(row.documento) as Map<String, dynamic>;
    final validator = await Ficha148Validator.desdeAssets();
    validator.validarDocumentoOExcepcion(doc);
    return conSnapshotCatalogos(doc);
  }

  Future<Map<String, dynamic>> conSnapshotCatalogos(Map<String, dynamic> documento) async {
    final ficha = Map<String, dynamic>.from(documento['ficha']);
    ficha['catalogosSnapshot'] = {'insumos': await listarInsumos(), 'tarifasSalario': await listarTarifas()};
    return {'schemaVersion': documento['schemaVersion'], 'ficha': ficha};
  }

  @override
  Future<List<Map<String, dynamic>>> listarInsumos() async => _listarCatalogo('insumo');
  @override
  Future<List<Map<String, dynamic>>> listarTarifas() async => _listarCatalogo('tarifa');

  Future<List<Map<String, dynamic>>> _listarCatalogo(String tipo) async => (await db.listarCatalogo(tipo))
      .map((e) => jsonDecode(e.documento) as Map<String, dynamic>).toList();

  @override
  Future<void> guardarInsumo(Insumo i) => db.guardarCatalogo(i.id, 'insumo', jsonEncode({
    'id': i.id, 'nombre': i.nombre, 'unidadMedida': i.unidadMedida, 'costoUnitario': i.costoUnitario.toJson()}));
  @override
  Future<void> guardarTarifa(TarifaSalario t) => db.guardarCatalogo(t.id, 'tarifa', jsonEncode({
    'id': t.id, 'cargo': t.cargo, 'tarifa': t.tarifa.toJson(), 'unidadTarifa': t.unidadTarifa}));

  Future<void> eliminarCatalogo(String id) => db.eliminarCatalogo(id);

}
