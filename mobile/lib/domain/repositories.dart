import 'models.dart';

abstract interface class FichasRepository {
  Future<List<FichaCosto>> listar();
  Future<void> guardar(FichaCosto ficha);
  Future<void> eliminar(String id);
  Future<void> importar(Map<String, dynamic> documento);
  Future<Map<String, dynamic>> exportar(String id);
}

abstract interface class CatalogosRepository {
  Future<List<Map<String, dynamic>>> listarInsumos();
  Future<void> guardarInsumo(Insumo insumo);
  Future<List<Map<String, dynamic>>> listarTarifas();
  Future<void> guardarTarifa(TarifaSalario tarifa);
}
