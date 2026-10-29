import 'package:uuid/uuid.dart';

const _uuid = Uuid();
enum Moneda { CUP, MLC }
enum EstadoFicha { borrador, finalizada }
enum CategoriaCosto {
  materias_primas_materiales,
  fuerza_trabajo_directa,
  otros_gastos_directos,
  gastos_indirectos_produccion,
}

class Importe {
  const Importe(this.valor, this.moneda);
  final double valor;
  final Moneda moneda;
  Map<String, dynamic> toJson() => {'valor': valor, 'moneda': moneda.name};
  factory Importe.fromJson(Map<String, dynamic> json) => Importe((json['valor'] as num).toDouble(), Moneda.values.byName(json['moneda']));
}

class PartidaCosto {
  PartidaCosto({required this.categoria, required this.descripcion, required this.cantidad,
    required this.unidadMedida, required this.costoUnitario, String? id, this.insumoId, this.observaciones = ''}) : id = id ?? _uuid.v4();
  final String id;
  final CategoriaCosto categoria;
  final String descripcion;
  final String? insumoId;
  final double cantidad;
  final String unidadMedida;
  final Importe costoUnitario;
  final String observaciones;
  Importe get subtotal => Importe(_round(cantidad * costoUnitario.valor), costoUnitario.moneda);
  Map<String, dynamic> toJson() => {'id': id, 'categoria': categoria.name, 'descripcion': descripcion,
    'insumoId': insumoId, 'cantidad': cantidad, 'unidadMedida': unidadMedida,
    'costoUnitario': costoUnitario.toJson(), 'subtotal': subtotal.toJson(), 'observaciones': observaciones};
  factory PartidaCosto.fromJson(Map<String, dynamic> j) => PartidaCosto(id: j['id'], categoria: CategoriaCosto.values.byName(j['categoria']),
    descripcion: j['descripcion'], insumoId: j['insumoId'], cantidad: (j['cantidad'] as num).toDouble(), unidadMedida: j['unidadMedida'],
    costoUnitario: Importe.fromJson(Map<String, dynamic>.from(j['costoUnitario'])), observaciones: j['observaciones'] ?? '');
}

class Coeficientes {
  const Coeficientes({this.coeficienteIndirecto, this.margenGanancia, this.unidadCoeficiente = 'porcentaje'});
  final double? coeficienteIndirecto;
  final double? margenGanancia;
  final String unidadCoeficiente;
  Map<String, dynamic> toJson() => {'coeficienteIndirecto': coeficienteIndirecto, 'margenGanancia': margenGanancia, 'unidadCoeficiente': unidadCoeficiente};
  factory Coeficientes.fromJson(Map<String, dynamic> json) => Coeficientes(
    coeficienteIndirecto: (json['coeficienteIndirecto'] as num?)?.toDouble(),
    margenGanancia: (json['margenGanancia'] as num?)?.toDouble(),
    unidadCoeficiente: json['unidadCoeficiente'] ?? 'porcentaje');
}

class FichaCosto {
  FichaCosto({required this.nombre, this.descripcion = '', this.monedaBase = Moneda.CUP,
    String? id, DateTime? fechaCreacion, DateTime? fechaActualizacion, this.estado = EstadoFicha.borrador,
    List<PartidaCosto>? partidas, this.coeficientes = const Coeficientes(),
    this.catalogosSnapshot = const {'insumos': <dynamic>[], 'tarifasSalario': <dynamic>[]}, this.extensionData = const {}})
    : id = id ?? _uuid.v4(), fechaCreacion = (fechaCreacion ?? DateTime.now().toUtc()).toIso8601String(),
      fechaActualizacion = (fechaActualizacion ?? DateTime.now().toUtc()).toIso8601String(), partidas = partidas ?? [];
  final String id;
  final String nombre;
  final String descripcion;
  final String fechaCreacion;
  final String fechaActualizacion;
  final EstadoFicha estado;
  final Moneda monedaBase;
  final List<PartidaCosto> partidas;
  final Coeficientes coeficientes;
  final Map<String, dynamic> catalogosSnapshot;
  final Map<String, dynamic> extensionData;

  Map<String, dynamic> get totales {
    // Keep independent currency ledgers; no implicit CUP/MLC conversion.
    final valores = {for (final c in CategoriaCosto.values) c.name: {for (final m in Moneda.values) m.name: 0.0}};
    for (final p in partidas) {
      valores[p.categoria.name]![p.costoUnitario.moneda.name] = valores[p.categoria.name]![p.costoUnitario.moneda.name]! + p.subtotal.valor;
    }
    final total = {for (final m in Moneda.values) m.name: 0.0};
    for (final categoria in valores.values) {
      for (final m in Moneda.values) { total[m.name] = total[m.name]! + categoria[m.name]!; }
    }
    Map<String, double>? precio;
    if (coeficientes.margenGanancia != null) {
      precio = {for (final m in Moneda.values) m.name: _round(coeficientes.unidadCoeficiente == 'porcentaje'
        ? total[m.name]! * (1 + coeficientes.margenGanancia! / 100)
        : total[m.name]! * coeficientes.margenGanancia!)};
    }
    return {'porCategoria': {for (final e in valores.entries) e.key: {for (final m in Moneda.values) m.name: _round(e.value[m.name]!) }},
      'costoTotal': {for (final m in Moneda.values) m.name: _round(total[m.name]!)}, 'precioCalculado': precio};
  }

  Map<String, dynamic> toDocument() => {'schemaVersion': 1, 'ficha': {'id': id, 'nombre': nombre, 'descripcion': descripcion,
    'fechaCreacion': fechaCreacion, 'fechaActualizacion': DateTime.now().toUtc().toIso8601String(), 'estado': estado.name,
    'monedaBase': monedaBase.name, 'partidas': partidas.map((p) => p.toJson()).toList(), 'catalogosSnapshot': catalogosSnapshot, 'coeficientes': coeficientes.toJson(),
    'totales': totales, 'extensionData': extensionData}};

  factory FichaCosto.fromDocument(Map<String, dynamic> d) {
    if (d['schemaVersion'] != 1) throw FormatException('schemaVersion no soportado');
    final j = Map<String, dynamic>.from(d['ficha']);
    return FichaCosto(id: j['id'], nombre: j['nombre'], descripcion: j['descripcion'] ?? '',
      fechaCreacion: DateTime.parse(j['fechaCreacion']), fechaActualizacion: DateTime.parse(j['fechaActualizacion']),
      estado: EstadoFicha.values.byName(j['estado']), monedaBase: Moneda.values.byName(j['monedaBase']),
      partidas: (j['partidas'] as List).map((p) => PartidaCosto.fromJson(Map<String, dynamic>.from(p))).toList(),
      coeficientes: Coeficientes.fromJson(Map<String, dynamic>.from(j['coeficientes'] ?? {})),
      catalogosSnapshot: Map<String, dynamic>.from(j['catalogosSnapshot'] ?? {'insumos': <dynamic>[], 'tarifasSalario': <dynamic>[]}),
      extensionData: Map<String, dynamic>.from(j['extensionData'] ?? {}));
  }
}

class Insumo {
  Insumo({required this.nombre, required this.unidadMedida, required this.costoUnitario, String? id}) : id = id ?? _uuid.v4();
  final String id; final String nombre; final String unidadMedida; final Importe costoUnitario;
}
class TarifaSalario {
  TarifaSalario({required this.cargo, required this.tarifa, required this.unidadTarifa, String? id}) : id = id ?? _uuid.v4();
  final String id; final String cargo; final Importe tarifa; final String unidadTarifa;
}

double _round(double value) => (value * 100).roundToDouble() / 100;
