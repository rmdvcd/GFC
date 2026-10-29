import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

import '../domain/models.dart';

/// Generador/widget PDF del formato referencial solicitado.
/// Los datos fuera del dominio actual se leen de `ficha.extensionData['anexoI']`.
/// Véase README/PDF para el contrato de extensión. No supone datos faltantes como cero.
class FichaCostoPdf extends pw.StatelessWidget {
  const FichaCostoPdf({required this.ficha, this.marcaAgua = false});
  final FichaCosto ficha;
  final bool marcaAgua;

  static const double _margen = 28.35; // 10 mm
  static const double _tamanoTitulo = 12;
  static const double _tamanoSubtitulo = 8;
  static const double _tamanoCuerpo = 7;
  static const String _pendiente = '[PENDIENTE]';
  static const List<double> _anchos = [34, 265, 78, 50, 170, 188];
  static final PdfColor _grisCabecera = PdfColor(0.898, 0.906, 0.922); // #E5E7EB
  static final PdfColor _grisGrupo = PdfColor(0.953, 0.961, 0.969); // #F3F4F6
  static final PdfColor _grisLinea = PdfColor(0.420, 0.443, 0.486); // #6B7280
  static final PdfColor _tinta = PdfColor(0.067, 0.094, 0.153); // #111827

  @override
  pw.Widget build(pw.Context context) => pw.Column(children: contenido());

  /// Widgets expuestos para permitir que `MultiPage` divida las tablas largas entre páginas.
  List<pw.Widget> contenido() {
    final anexo = _anexo;
    final filasAnexo = _map(anexo['filas']);
    final fuentes = <String, _FuenteFila>{
      '1': _fuente('1', filasAnexo, CategoriaCosto.materias_primas_materiales),
      '2': _fuente('2', filasAnexo, null),
      '3': _fuente('3', filasAnexo, null),
      '4': _fuente('4', filasAnexo, CategoriaCosto.fuerza_trabajo_directa),
      '5': _fuente('5', filasAnexo, CategoriaCosto.gastos_indirectos_produccion),
      '6': _fuente('6', filasAnexo, null),
      '7': _fuente('7', filasAnexo, null),
      '8': _fuente('8', filasAnexo, null),
    };
    final otrosDirectos = ficha.partidas.where((p) => p.categoria == CategoriaCosto.otros_gastos_directos).map(_lineaModelo).toList();
    final filasCompletas = List.generate(8, (i) => fuentes['${i + 1}']!.conocida).every((x) => x) && otrosDirectos.isEmpty;
    final totalesFila = <String, Map<String, double>>{
      for (final e in fuentes.entries)
        if (e.value.conocida) e.key: _sumar(e.value.lineas),
    };
    final costo = {for (final moneda in Moneda.values) moneda.name: 0.0};
    if (filasCompletas) {
      for (final fila in List.generate(8, (i) => '${i + 1}')) {
        for (final moneda in Moneda.values) {
          costo[moneda.name] = costo[moneda.name]! + totalesFila[fila]![moneda.name]!;
        }
      }
    }
    final margen = _map(anexo['margenUtilidad']);
    final importeMargen = _map(margen['importe']);
    final baseAutorizada = _stringValue(margen['baseAutorizada']);
    final margenConocido = baseAutorizada.isNotEmpty && Moneda.values.every((m) => _numero(importeMargen[m.name]) != null && _numero(importeMargen[m.name])! >= 0);
    final importesMargen = {for (final m in Moneda.values) m.name: _numero(importeMargen[m.name]) ?? 0.0};
    final precio = {for (final m in Moneda.values) m.name: costo[m.name]! + importesMargen[m.name]!};
    final precioConocido = filasCompletas && margenConocido;

    final widgets = <pw.Widget>[
      pw.Text('FICHA DE COSTOS Y GASTOS DE PRODUCTOS Y SERVICIOS PARA LA EVALUACIÓN DE PRECIOS Y TARIFAS',
          textAlign: pw.TextAlign.center, style: pw.TextStyle(font: pw.Font.helveticaBold(), fontSize: _tamanoTitulo, color: _tinta)),
      pw.SizedBox(height: 3),
      pw.Text('Conforme a la Resolución 148/2023 del Ministerio de Finanzas y Precios · Modelo referencial sujeto a verificación del Anexo I',
          textAlign: pw.TextAlign.center, style: pw.TextStyle(font: pw.Font.helvetica(), fontSize: _tamanoSubtitulo, color: _tinta)),
      pw.SizedBox(height: 8),
      _tablaMetadatos(anexo),
      pw.SizedBox(height: 8),
      _tablaCostos(fuentes, totalesFila, filasCompletas, otrosDirectos, costo, margen, margenConocido, importesMargen, precio, precioConocido),
      pw.SizedBox(height: 8),
    ];
    if (!filasCompletas) {
      widgets.add(_texto('Nota: faltan datos o confirmaciones para una o más filas. El costo total y el precio se dejan como [PENDIENTE]; no se presumen como cero.', size: 6.5));
    }
    if (otrosDirectos.isNotEmpty) {
      widgets.add(_texto('Nota: la ficha contiene otros gastos directos sin casilla identificada en la estructura solicitada. No se incorporan al subtotal hasta su clasificación.', size: 6.5));
    }
    widgets.add(_texto('Plantilla referencial generada por FichaCosto. Verifique campos, desglose, base autorizada y metodología contra el texto oficial vigente antes de presentar ante una autoridad.', size: 6.5));
    widgets.add(pw.SizedBox(height: 12));
    widgets.add(_tablaFirmas(_map(anexo['firmas'])));
    widgets.add(pw.SizedBox(height: 5));
    widgets.add(_texto('Fecha de elaboración: ${_stringValue(anexo['fechaConfeccion']).isEmpty ? ficha.fechaCreacion : anexo['fechaConfeccion']}     Sello de la entidad: [PENDIENTE / SI APLICA]', size: 6.5));
    return widgets;
  }

  Future<Uint8List> generar() async {
    final documento = pw.Document(
      theme: pw.ThemeData.withFont(base: pw.Font.helvetica(), bold: pw.Font.helveticaBold()),
      title: 'Ficha de Costos y Gastos',
      author: 'FichaCosto',
    );
    final printableWidth = PdfPageFormat.a4.landscape.width - 2 * _margen;
    documento.addPage(pw.MultiPage(
      pageTheme: pw.PageTheme(
        pageFormat: PdfPageFormat.a4.landscape,
        margin: const pw.EdgeInsets.fromLTRB(_margen, _margen, _margen, _margen + 11.34),
        buildBackground: (context) => marcaAgua
            ? pw.FullPage(ignoreMargins: true, child: pw.Center(child: pw.Transform.rotate(
                angle: -0.56, child: pw.Opacity(opacity: 0.18, child: pw.Text('VERSIÓN NO LICENCIADA',
                  style: pw.TextStyle(font: pw.Font.helveticaBold(), fontSize: 32, color: PdfColors.red))))))
            : pw.SizedBox(),
      ),
      build: (_) => contenido(),
      footer: (context) => pw.Align(
        alignment: pw.Alignment.centerRight,
        child: pw.Text('Ficha ${ficha.id} · Página ${context.pageNumber}',
            style: pw.TextStyle(font: pw.Font.helvetica(), fontSize: 6.5, color: _grisLinea)),
      ),
    ));
    // Avoid an unused-width lint while documenting the same printable width used by ReportLab.
    assert(printableWidth > 0);
    return Uint8List.fromList(await documento.save());
  }

  Future<void> previsualizar() => Printing.layoutPdf(onLayout: (_) => generar());

  Map<String, dynamic> get _anexo => _map(ficha.extensionData['anexoI']);

  _FuenteFila _fuente(String numero, Map<String, dynamic> anexo, CategoriaCosto? categoria) {
    if (anexo.containsKey(numero)) {
      final value = anexo[numero];
      if (value is List && value.every((e) => e is Map)) {
        return _FuenteFila(true, value.map((e) => Map<String, dynamic>.from(e as Map)).toList(), true);
      }
      return const _FuenteFila(false, [], true);
    }
    if (categoria == null) return const _FuenteFila(false, [], false);
    final lines = ficha.partidas.where((p) => p.categoria == categoria).map(_lineaModelo).toList();
    return _FuenteFila(lines.isNotEmpty, lines, false);
  }

  Map<String, dynamic> _lineaModelo(PartidaCosto p) => {
    'concepto': p.descripcion,
    'unidadMedida': p.unidadMedida,
    'cantidad': p.cantidad,
    'precioUnitario': {'valor': p.costoUnitario.valor, 'moneda': p.costoUnitario.moneda.name},
    'importe': {'valor': p.subtotal.valor, 'moneda': p.subtotal.moneda.name},
  };

  Map<String, double> _sumar(List<Map<String, dynamic>> lines) {
    final result = {for (final m in Moneda.values) m.name: 0.0};
    for (final line in lines) {
      final importe = _map(line['importe']);
      final precio = _map(line['precioUnitario']);
      final cantidad = _numero(line['cantidad']);
      final moneda = importe['moneda'] ?? precio['moneda'];
      final amount = _numero(importe['valor']) ?? ((_numero(precio['valor']) != null && cantidad != null) ? _numero(precio['valor'])! * cantidad : null);
      if (moneda is String && result.containsKey(moneda) && amount != null) result[moneda] = result[moneda]! + amount;
    }
    return {for (final e in result.entries) e.key: (e.value * 100).roundToDouble() / 100};
  }

  pw.Widget _tablaMetadatos(Map<String, dynamic> anexo) {
    final rows = <List<String>>[
      ['Entidad', _valor(anexo['nombreEntidad']), 'Código de ficha (UUID)', ficha.id],
      ['Fecha de confección', _valor(anexo['fechaConfeccion'], fallback: ficha.fechaCreacion), 'Período de vigencia', _valor(anexo['periodoVigencia'])],
      ['Actividad económica', _valor(anexo['actividadEconomica']), 'Producto / servicio', _valor(ficha.nombre)],
    ];
    return pw.Table(
      columnWidths: const {0: pw.FixedColumnWidth(90), 1: pw.FixedColumnWidth(192.7), 2: pw.FixedColumnWidth(105), 3: pw.FixedColumnWidth(397.5)},
      border: pw.TableBorder.all(color: _grisLinea, width: 0.35),
      children: rows.map((row) => pw.TableRow(children: [
        _celda(row[0], bold: true, fill: _grisCabecera), _celda(row[1]), _celda(row[2], bold: true, fill: _grisCabecera), _celda(row[3]),
      ])).toList(),
    );
  }

  pw.Widget _tablaCostos(Map<String, _FuenteFila> fuentes, Map<String, Map<String, double>> totalsByRow,
      bool rowsKnown, List<Map<String, dynamic>> otherDirect, Map<String, double> cost,
      Map<String, dynamic> margin, bool marginKnown, Map<String, double> marginAmount,
      Map<String, double> price, bool priceKnown) {
    final printableWidth = PdfPageFormat.a4.landscape.width - 2 * _margen;
    final factor = printableWidth / _anchos.fold<double>(0, (a, b) => a + b);
    final labels = <String, String>{
      '1': 'Materias primas y materiales', '2': 'Combustibles', '3': 'Energía',
      '4': 'Gastos de fuerza de trabajo (salarios y estimulación, según corresponda)',
      '5': 'Gastos indirectos de producción', '6': 'Gastos generales y de administración',
      '7': 'Gastos de distribución y ventas', '8': 'Gastos bancarios',
    };
    final rows = <pw.TableRow>[
      _fila(['No. de fila', 'Concepto / Elemento del Costo', 'Unidad de Medida', 'Cantidad', 'Precio Unitario (CUP/MLC)', 'Importe Total (CUP/MLC)'], header: true),
    ];
    for (var n = 1; n <= 8; n++) {
      final number = '$n';
      final source = fuentes[number]!;
      rows.add(_fila([number, labels[number]!, '', '', '', source.conocida ? _formatTotals(totalsByRow[number]!) : _pendiente], group: true));
      if (source.conocida && source.lineas.isNotEmpty) {
        for (final line in source.lineas) { rows.add(_fila(_lineaPdf(line))); }
        if (number == '5' && !source.explicita) {
          for (final sub in ['Depreciación', 'Mantenimiento y reparaciones', 'Otros conceptos indirectos']) {
            rows.add(_fila(['', '$sub — $_pendiente (desglose no disponible)', _pendiente, _pendiente, _pendiente, _pendiente]));
          }
        }
      } else if (source.conocida) {
        rows.add(_fila(['', 'Sin partidas consignadas', '—', '—', '—', '0.00 CUP\n0.00 MLC']));
      } else if (number == '5') {
        for (final sub in ['Depreciación', 'Mantenimiento y reparaciones', 'Otros conceptos indirectos']) {
          rows.add(_fila(['', '$sub — $_pendiente', _pendiente, _pendiente, _pendiente, _pendiente]));
        }
      } else {
        rows.add(_fila(['', _pendiente, _pendiente, _pendiente, _pendiente, _pendiente]));
      }
    }
    if (otherDirect.isNotEmpty) {
      rows.add(_fila(['—', 'Otros gastos directos registrados; pendiente de clasificar en el modelo solicitado', '', '', '', _formatTotals(_sumar(otherDirect))], group: true));
    }
    rows.add(_fila(['9', 'COSTO TOTAL DE PRODUCCIÓN (suma de filas 1 a 8)', '', '', '', rowsKnown ? _formatTotals(cost) : _pendiente], group: true));
    final pct = _numero(margin['porcentaje']);
    final marginLabel = 'Margen de utilidad sobre base autorizada${_stringValue(margin['baseAutorizada']).isNotEmpty ? ': ${margin['baseAutorizada']}' : ''}';
    rows.add(_fila(['10', marginLabel, '', '', pct == null ? _pendiente : '${_fmt(pct)}%', marginKnown ? _formatTotals(marginAmount) : _pendiente], group: true));
    rows.add(_fila(['11', 'PRECIO O TARIFA TOTAL (costo total + margen)', '', '', '', priceKnown ? _formatTotals(price) : _pendiente], group: true));
    return pw.Table(
      columnWidths: {for (var i = 0; i < _anchos.length; i++) i: pw.FixedColumnWidth(_anchos[i] * factor)},
      border: pw.TableBorder.all(color: _grisLinea, width: 0.35),
      children: rows,
    );
  }

  pw.TableRow _fila(List<String> values, {bool header = false, bool group = false}) => pw.TableRow(
    decoration: header ? pw.BoxDecoration(color: _grisCabecera) : (group ? pw.BoxDecoration(color: _grisGrupo) : null),
    children: List.generate(6, (i) => _celda(values[i], bold: header || (group && (i == 0 || i == 1 || i == 5)),
      align: i == 0 ? pw.Alignment.center : (i >= 3 ? pw.Alignment.centerRight : pw.Alignment.centerLeft),
      fontSize: header ? 6.7 : (group ? _tamanoCuerpo : 6.5))),
  );

  pw.Widget _celda(String text, {bool bold = false, PdfColor? fill, pw.Alignment align = pw.Alignment.centerLeft, double fontSize = 6.5}) => pw.Container(
    alignment: align,
    padding: const pw.EdgeInsets.symmetric(horizontal: 4, vertical: 3),
    color: fill,
    child: pw.Text(text, style: pw.TextStyle(font: bold ? pw.Font.helveticaBold() : pw.Font.helvetica(), fontSize: fontSize, color: _tinta)),
  );

  pw.Widget _tablaFirmas(Map<String, dynamic> firmantes) {
    final columns = <String>[];
    for (final entry in [
      ('elaboradoPor', 'ELABORADO POR'), ('revisadoPor', 'REVISADO POR'), ('aprobadoPor', 'APROBADO POR'),
    ]) {
      final person = _map(firmantes[entry.$1]);
      columns.add('${entry.$2}\nNombre: ${_valor(person['nombre'])}\nCargo: ${_valor(person['cargo'])}\n\nFirma: __________________________');
    }
    return pw.Table(
      columnWidths: const {0: pw.FlexColumnWidth(), 1: pw.FlexColumnWidth(), 2: pw.FlexColumnWidth()},
      border: pw.TableBorder.all(color: _grisLinea, width: 0.35),
      children: [pw.TableRow(children: columns.map((s) => pw.Container(height: 62, padding: const pw.EdgeInsets.all(5), alignment: pw.Alignment.topLeft,
        child: pw.Text(s, style: pw.TextStyle(font: pw.Font.helvetica(), fontSize: 7, lineSpacing: 2)))).toList())],
    );
  }

  List<String> _lineaPdf(Map<String, dynamic> line) {
    final concept = _valor(line['concepto']);
    final unit = _valor(line['unidadMedida']);
    final quantity = _numero(line['cantidad']);
    final price = _map(line['precioUnitario']);
    final amount = _map(line['importe']);
    final currency = price['moneda'] ?? amount['moneda'];
    final unitPrice = _numero(price['valor']);
    final amountValue = _numero(amount['valor']) ?? ((unitPrice != null && quantity != null) ? unitPrice * quantity : null);
    return ['', concept, unit, quantity == null ? _pendiente : _fmt(quantity),
      unitPrice == null || currency is! String ? _pendiente : '${_fmt(unitPrice)} $currency',
      amountValue == null || currency is! String ? _pendiente : '${_fmt(amountValue)} $currency'];
  }

  pw.Widget _texto(String text, {double size = _tamanoCuerpo}) => pw.Text(text,
      style: pw.TextStyle(font: pw.Font.helvetica(), fontSize: size, color: _tinta, lineSpacing: 1.2));

  String _formatTotals(Map<String, double> totals) => '${_fmt(totals['CUP'] ?? 0)} CUP\n${_fmt(totals['MLC'] ?? 0)} MLC';
  String _valor(dynamic value, {String fallback = _pendiente}) => value is String && value.trim().isNotEmpty ? value.trim() : fallback;
  String _stringValue(dynamic value) => value is String ? value.trim() : '';
  double? _numero(dynamic value) => value is num && value.isFinite ? value.toDouble() : null;
  String _fmt(double value) => value.toStringAsFixed(2);
  Map<String, dynamic> _map(dynamic value) => value is Map ? Map<String, dynamic>.from(value) : <String, dynamic>{};
}

class _FuenteFila {
  const _FuenteFila(this.conocida, this.lineas, this.explicita);
  final bool conocida;
  final List<Map<String, dynamic>> lineas;
  final bool explicita;
}
