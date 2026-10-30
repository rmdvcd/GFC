import 'dart:convert';
import 'dart:io';
import 'package:csv/csv.dart';
import 'package:path_provider/path_provider.dart';
import '../domain/models.dart';
import 'ficha_costo_pdf.dart';
import 'xlsx_writer.dart';

class ExportacionesDocumento {
  static Future<File> _file(FichaCosto ficha, String ext) async {
    final dir = await getApplicationDocumentsDirectory();
    final safe = ficha.nombre.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_');
    return File('${dir.path}/$safe.$ext');
  }
  static Future<File> csv(FichaCosto ficha) async {
    final rows = <List<dynamic>>[['categoria', 'descripcion', 'cantidad', 'unidadMedida', 'costoUnitario', 'moneda', 'subtotal']];
    rows.addAll(ficha.partidas.map((p) => [p.categoria.name, p.descripcion, p.cantidad, p.unidadMedida, p.costoUnitario.valor, p.costoUnitario.moneda.name, p.subtotal.valor]));
    final file = await _file(ficha, 'csv');
    return file.writeAsString(const ListToCsvConverter(fieldDelimiter: ';').convert(rows), encoding: utf8);
  }
  static Future<File> excel(FichaCosto ficha) async {
    final rows = <List<Object?>>[
      ['Categoría', 'Descripción', 'Cantidad', 'Unidad', 'Costo unitario', 'Moneda', 'Subtotal'],
      for (final p in ficha.partidas)
        [
          p.categoria.name,
          p.descripcion,
          p.cantidad,
          p.unidadMedida,
          p.costoUnitario.valor,
          p.costoUnitario.moneda.name,
          p.subtotal.valor,
        ],
    ];
    final file = await _file(ficha, 'xlsx');
    return file.writeAsBytes(
      buildXlsxWorkbook(
        sheetName: 'Partidas',
        rows: rows,
        columnWidths: const <double>[16, 40, 12, 14, 16, 10, 14],
      ),
      flush: true,
    );
  }
  static Future<File> pdf(FichaCosto ficha, {bool marcaAgua = false}) async {
    final file = await _file(ficha, 'pdf');
    final bytes = await FichaCostoPdf(ficha: ficha, marcaAgua: marcaAgua).generar();
    return file.writeAsBytes(bytes, flush: true);
  }

  static Future<void> previsualizarPdf(FichaCosto ficha, {bool marcaAgua = false}) =>
      FichaCostoPdf(ficha: ficha, marcaAgua: marcaAgua).previsualizar();
}
