import 'dart:convert';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:ficha_costo_mobile/data/xlsx_writer.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  Archive openArchive(Uint8List bytes) {
    final archive = ZipDecoder().decodeBytes(bytes);
    expect(archive.files.every((file) => file.isFile), isTrue);
    return archive;
  }

  ArchiveFile fileOf(Archive archive, String name) =>
      archive.files.firstWhere((file) => file.name == name);

  String readPart(Archive archive, String name) {
    final stream = fileOf(archive, name).getContent()!;
    final builder = BytesBuilder(copy: false);
    while (!stream.isEOS) {
      final remaining = stream.length;
      final chunk = stream.readBytes(remaining > 8192 ? 8192 : remaining);
      builder.add(chunk.toUint8List());
    }
    return utf8.decode(builder.takeBytes());
  }

  test('empaqueta las partes OOXML obligatorias de un libro de una hoja', () {
    final bytes = buildXlsxWorkbook(sheetName: 'Partidas', rows: [
      ['Descripción', 'Cantidad'],
      ['Cemento', 2.0],
    ]);
    final archive = openArchive(bytes);
    expect(archive.files.map((file) => file.name).toList(), [
      '[Content_Types].xml',
      '_rels/.rels',
      'xl/workbook.xml',
      'xl/_rels/workbook.xml.rels',
      'xl/styles.xml',
      'xl/worksheets/sheet1.xml',
    ]);
    expect(readPart(archive, 'xl/workbook.xml'), contains('name="Partidas"'));
    expect(readPart(archive, 'xl/_rels/workbook.xml.rels'), contains('worksheets/sheet1.xml'));
    expect(readPart(archive, '[Content_Types].xml'), contains('/xl/worksheets/sheet1.xml'));
  });

  test('escribe texto como cadena en línea y números como valores numéricos', () {
    final bytes = buildXlsxWorkbook(sheetName: 'Partidas', rows: [
      ['Descripción & unidad', 'Cantidad'],
      ['Varilla 3/8" <A>', 12.5],
      [null, 3],
    ]);
    final sheet = readPart(openArchive(bytes), 'xl/worksheets/sheet1.xml');

    expect(sheet, contains('<dimension ref="A1:B3"/>'));
    expect(sheet, contains('<c r="A2" t="inlineStr"><is><t xml:space="preserve">'
        'Varilla 3/8&quot; &lt;A&gt;</t></is></c>'));
    expect(sheet, contains('<c r="A1" t="inlineStr"><is><t xml:space="preserve">'
        'Descripción &amp; unidad</t></is></c>'));
    expect(sheet, contains('<c r="B2"><v>12.5</v></c>'));
    expect(sheet, contains('<c r="B3"><v>3</v></c>'));
    expect(sheet, isNot(contains('r="A3"')));
  });

  test('respeta anchos de columna y rechaza nombres de hoja inválidos', () {
    final sheet = readPart(
      openArchive(buildXlsxWorkbook(
        sheetName: 'Partidas',
        rows: const <List<Object?>>[['a']],
        columnWidths: const <double>[16, 12.5],
      )),
      'xl/worksheets/sheet1.xml',
    );
    expect(sheet, contains('<col min="1" max="1" width="16" customWidth="1"/>'));
    expect(sheet, contains('<col min="2" max="2" width="12.5" customWidth="1"/>'));

    expect(() => buildXlsxWorkbook(sheetName: '', rows: const <List<Object?>>[]), throwsArgumentError);
    expect(() => buildXlsxWorkbook(sheetName: 'Hoja[1]', rows: const <List<Object?>>[]), throwsArgumentError);
  });
}
