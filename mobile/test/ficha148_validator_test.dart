import 'dart:convert';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ficha_costo_mobile/data/ficha148_validator.dart';
import 'package:ficha_costo_mobile/domain/models.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Ficha148Validator validator;
  setUpAll(() async {
    validator = await Ficha148Validator.desdeAssets();
  });

  Uint8List buildPackage(Map<String, dynamic> document, {String fichaName = 'ficha.json'}) {
    final manifest = {
      'format': 'ficha148', 'formatVersion': 1, 'schemaVersion': document['schemaVersion'], 'document': 'ficha.json',
    };
    final manifestBytes = utf8.encode(jsonEncode(manifest));
    final fichaBytes = utf8.encode(jsonEncode(document));
    final archive = Archive()
      ..addFile(ArchiveFile('manifest.json', manifestBytes.length, manifestBytes))
      ..addFile(ArchiveFile(fichaName, fichaBytes.length, fichaBytes));
    return Uint8List.fromList(ZipEncoder().encode(archive)!);
  }

  test('accepts a schema-valid ficha148 and returns its summary without DB writes', () {
    final document = FichaCosto(nombre: 'Prueba').toDocument();
    final summary = validator.validarBytes(buildPackage(document));
    expect(summary.document, document);
    expect(summary.entity, '[PENDIENTE]');
    expect(summary.period, '[PENDIENTE]');
    expect(summary.cup, 0);
  });

  test('returns Spanish schema messages for invalid semantic data', () {
    final document = FichaCosto(nombre: 'Prueba').toDocument();
    (document['ficha'] as Map<String, dynamic>)['nombre'] = '';
    final messages = validator.validarDocumento(document);
    expect(messages, isNotEmpty);
    expect(messages.any((message) => message.contains('nombre de la ficha')), isTrue);
  });

  test('rejects bad ZIP signature with a friendly message', () {
    expect(
      () => validator.validarBytes(Uint8List.fromList([1, 2, 3, 4])),
      throwsA(isA<Ficha148ValidationException>().having((e) => e.packageError, 'packageError', isTrue)),
    );
  });

  test('rejects unexpected path names before reading payload', () {
    final document = FichaCosto(nombre: 'Prueba').toDocument();
    final bytes = buildPackage(document, fichaName: '../ficha.json');
    expect(
      () => validator.validarBytes(bytes),
      throwsA(isA<Ficha148ValidationException>().having((e) => e.packageError, 'packageError', isTrue)),
    );
  });
}
