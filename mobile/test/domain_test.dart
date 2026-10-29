import 'package:flutter_test/flutter_test.dart';
import 'package:ficha_costo_mobile/domain/models.dart';

void main() {
  test('mantiene totales CUP y MLC independientes y calcula un margen estimado', () {
    final ficha = FichaCosto(nombre: 'Ensayo', partidas: [
      PartidaCosto(categoria: CategoriaCosto.materias_primas_materiales, descripcion: 'Material CUP', cantidad: 2, unidadMedida: 'u', costoUnitario: const Importe(10, Moneda.CUP)),
      PartidaCosto(categoria: CategoriaCosto.otros_gastos_directos, descripcion: 'Material MLC', cantidad: 1, unidadMedida: 'u', costoUnitario: const Importe(4, Moneda.MLC)),
    ], coeficientes: const Coeficientes(margenGanancia: 10));
    expect(ficha.totales['costoTotal'], {'CUP': 20.0, 'MLC': 4.0});
    expect(ficha.totales['precioCalculado'], {'CUP': 22.0, 'MLC': 4.4});
  });

  test('serializa e importa la versión 1 del contrato', () {
    final ficha = FichaCosto(nombre: 'Ficha de prueba');
    final restored = FichaCosto.fromDocument(ficha.toDocument());
    expect(restored.id, ficha.id);
    expect(restored.nombre, ficha.nombre);
    expect(restored.estado, EstadoFicha.borrador);
  });
}
