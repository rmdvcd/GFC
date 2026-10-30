import 'dart:convert';
import 'dart:typed_data';

import 'package:archive/archive.dart';

/// Generador mínimo de libros `.xlsx` de una sola hoja.
///
/// Se usa en lugar de `package:excel` porque esa dependencia fija
/// `archive: ^3.6.1` y la app necesita `archive: ^4.x` para leer los paquetes
/// `.ficha148` y los respaldos por bloques con límites de tamaño. Un `.xlsx` es
/// un ZIP con partes XML, así que basta con escribirlas y empaquetarlas con
/// `package:archive`.
///
/// Decisiones deliberadas:
/// - Los textos van como cadenas en línea (`inlineStr`), sin `sharedStrings.xml`.
/// - Valores numéricos se escriben como número (`<v>`), no como texto, para que
///   Excel pueda sumarlos.
/// - Se descartan caracteres de control y surrogates sueltos, que XML 1.0 no
///   admite y que romperían el archivo.
/// - El contenido de cada parte se serializa en orden fijo, por lo que la misma
///   entrada produce exactamente los mismos bytes.

const String _xmlHeader = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';

const String _mainNamespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
const String _relationshipNamespace = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const String _packageRelationshipNamespace = 'http://schemas.openxmlformats.org/package/2006/relationships';
const String _contentTypesNamespace = 'http://schemas.openxmlformats.org/package/2006/content-types';

/// Límites del formato `.xlsx`. Se comprueban antes de generar el ZIP para no
/// producir un archivo que Excel rechazaría.
const int xlsxMaxRows = 1048576;
const int xlsxMaxColumns = 16384;

/// Construye un libro `.xlsx` con una hoja llamada [sheetName].
///
/// Cada fila de [rows] es una lista de celdas; `null` deja la celda vacía,
/// `num` se escribe como número, `bool` como booleano y cualquier otro valor
/// como texto. [columnWidths] es opcional: si se indica, se aplica el ancho (en
/// caracteres) a cada columna, en orden.
Uint8List buildXlsxWorkbook({
  required String sheetName,
  required List<List<Object?>> rows,
  List<double>? columnWidths,
}) {
  _checkSheetName(sheetName);
  if (rows.length > xlsxMaxRows) {
    throw ArgumentError('La hoja supera el máximo de $xlsxMaxRows filas.');
  }

  final sheetData = StringBuffer();
  var lastRow = 0;
  var lastColumn = 0;
  for (var rowIndex = 0; rowIndex < rows.length; rowIndex++) {
    final row = rows[rowIndex];
    if (row.length > xlsxMaxColumns) {
      throw ArgumentError('La fila ${rowIndex + 1} supera el máximo de $xlsxMaxColumns columnas.');
    }
    final rowNumber = rowIndex + 1;
    final cells = StringBuffer();
    for (var columnIndex = 0; columnIndex < row.length; columnIndex++) {
      final value = row[columnIndex];
      if (value == null) continue;
      final reference = '${_columnName(columnIndex + 1)}$rowNumber';
      if (value is bool) {
        cells.write('<c r="$reference" t="b"><v>${value ? 1 : 0}</v></c>');
      } else if (value is num) {
        final text = _numberText(value);
        if (text == null) continue;
        cells.write('<c r="$reference"><v>$text</v></c>');
      } else {
        cells.write('<c r="$reference" t="inlineStr"><is><t xml:space="preserve">'
            '${_escapeXml(value.toString())}</t></is></c>');
      }
      if (columnIndex + 1 > lastColumn) lastColumn = columnIndex + 1;
      lastRow = rowNumber;
    }
  }

  final dimension = lastRow == 0 || lastColumn == 0
      ? 'A1'
      : 'A1:${_columnName(lastColumn)}$lastRow';
  final columns = columnWidths == null || columnWidths.isEmpty
      ? ''
      : '<cols>${[
          for (var i = 0; i < columnWidths.length && i < xlsxMaxColumns; i++)
            '<col min="${i + 1}" max="${i + 1}" width="${_widthText(columnWidths[i])}" customWidth="1"/>',
        ].join()}</cols>';

  final worksheetXml = '$_xmlHeader'
      '<worksheet xmlns="$_mainNamespace">'
      '<dimension ref="$dimension"/>'
      '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
      '<sheetFormatPr defaultRowHeight="15"/>'
      '$columns'
      '<sheetData>$sheetData</sheetData>'
      '</worksheet>';

  final workbookXml = '$_xmlHeader'
      '<workbook xmlns="$_mainNamespace" xmlns:r="$_relationshipNamespace">'
      '<bookViews><workbookView/></bookViews>'
      '<sheets><sheet name="${_escapeXml(sheetName)}" sheetId="1" r:id="rId1"/></sheets>'
      '</workbook>';

  final workbookRelationshipsXml = '$_xmlHeader'
      '<Relationships xmlns="$_packageRelationshipNamespace">'
      '<Relationship Id="rId1" Type="$_relationshipNamespace/worksheet" Target="worksheets/sheet1.xml"/>'
      '<Relationship Id="rId2" Type="$_relationshipNamespace/styles" Target="styles.xml"/>'
      '</Relationships>';

  final packageRelationshipsXml = '$_xmlHeader'
      '<Relationships xmlns="$_packageRelationshipNamespace">'
      '<Relationship Id="rId1" Type="$_relationshipNamespace/officeDocument" Target="xl/workbook.xml"/>'
      '</Relationships>';

  final contentTypesXml = '$_xmlHeader'
      '<Types xmlns="$_contentTypesNamespace">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
      '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
      '</Types>';

  // Estilos mínimos: fuente, relleno obligatorio `gray125`, borde y estilo
  // normal. Sin esta parte Excel advierte que el libro está dañado.
  final stylesXml = '$_xmlHeader'
      '<styleSheet xmlns="$_mainNamespace">'
      '<fonts count="1"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
      '<fills count="2"><fill><patternFill patternType="none"/></fill>'
      '<fill><patternFill patternType="gray125"/></fill></fills>'
      '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
      '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
      '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
      '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
      '</styleSheet>';

  final archive = Archive();
  void addPart(String path, String xml) {
    final bytes = utf8.encode(xml);
    archive.addFile(ArchiveFile(path, bytes.length, bytes));
  }

  addPart('[Content_Types].xml', contentTypesXml);
  addPart('_rels/.rels', packageRelationshipsXml);
  addPart('xl/workbook.xml', workbookXml);
  addPart('xl/_rels/workbook.xml.rels', workbookRelationshipsXml);
  addPart('xl/styles.xml', stylesXml);
  addPart('xl/worksheets/sheet1.xml', worksheetXml);

  final List<int>? encoded = ZipEncoder().encode(archive);
  if (encoded == null) {
    throw StateError('No se pudo empaquetar el libro XLSX.');
  }
  return encoded is Uint8List ? encoded : Uint8List.fromList(encoded);
}

/// Nombre de columna en notación A1 (1 -> `A`, 27 -> `AA`).
String _columnName(int index) {
  var value = index;
  final codes = <int>[];
  while (value > 0) {
    codes.add(0x41 + (value - 1) % 26);
    value = (value - 1) ~/ 26;
  }
  return String.fromCharCodes(codes.reversed);
}

/// Representación decimal de [value] dentro de una celda numérica.
/// Devuelve `null` para valores no finitos, que no son representables en XML.
String? _numberText(num value) {
  if (value is int) return value.toString();
  final decimal = value.toDouble();
  if (!decimal.isFinite) return null;
  if (decimal == decimal.truncateToDouble() && decimal.abs() < 1e15) {
    return decimal.toInt().toString();
  }
  final text = decimal.toString();
  // `toString` puede usar notación científica; se expande a decimal simple
  // porque no todos los lectores la aceptan en `<v>`.
  if (text.contains('e') || text.contains('E')) return decimal.toStringAsFixed(12);
  return text;
}

String _widthText(double width) {
  if (!width.isFinite || width <= 0) return '10';
  if (width == width.truncateToDouble()) return width.toInt().toString();
  return width.toString();
}

String _escapeXml(String value) {
  final buffer = StringBuffer();
  for (final rune in value.runes) {
    if (rune == 0x09 || rune == 0x0A || rune == 0x0D) {
      buffer.writeCharCode(rune);
    } else if (rune == 0x26) {
      buffer.write('&amp;');
    } else if (rune == 0x3C) {
      buffer.write('&lt;');
    } else if (rune == 0x3E) {
      buffer.write('&gt;');
    } else if (rune == 0x22) {
      buffer.write('&quot;');
    } else if (rune == 0x27) {
      buffer.write('&apos;');
    } else if (rune < 0x20 || (rune >= 0xD800 && rune <= 0xDFFF) || rune == 0xFFFE || rune == 0xFFFF) {
      // XML 1.0 no admite caracteres de control ni surrogates sueltos.
      continue;
    } else {
      buffer.writeCharCode(rune);
    }
  }
  return buffer.toString();
}

void _checkSheetName(String name) {
  final trimmed = name.trim();
  if (trimmed.isEmpty) {
    throw ArgumentError('El nombre de la hoja no puede estar vacío.');
  }
  if (trimmed.length > 31) {
    throw ArgumentError('El nombre de la hoja no puede superar 31 caracteres.');
  }
  if (RegExp(r'[\[\]:*?/\\]').hasMatch(name)) {
    throw ArgumentError('El nombre de la hoja no admite los caracteres [ ] : * ? / \\');
  }
}
