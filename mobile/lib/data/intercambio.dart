import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:path_provider/path_provider.dart';

import 'ficha148_validator.dart';

/// Crea/lee el contenedor interoperable. Toda importación valida ZIP y JSON antes
/// de devolver un documento; este servicio no escribe en la base de datos.
class IntercambioFicha148 {
  static Future<File> exportar(Map<String, dynamic> documento, {String? destino}) async {
    final validator = await Ficha148Validator.desdeAssets();
    validator.validarDocumentoOExcepcion(documento);
    final manifest = {
      'format': 'ficha148',
      'formatVersion': 1,
      'schemaVersion': documento['schemaVersion'],
      'document': 'ficha.json',
      'producer': 'FichaCosto Mobile',
      'exportedAt': DateTime.now().toUtc().toIso8601String(),
    };
    final archive = Archive();
    final manifestBytes = utf8.encode(const JsonEncoder.withIndent('  ').convert(manifest));
    final fichaBytes = utf8.encode(const JsonEncoder.withIndent('  ').convert(documento));
    archive.addFile(ArchiveFile('manifest.json', manifestBytes.length, manifestBytes));
    archive.addFile(ArchiveFile('ficha.json', fichaBytes.length, fichaBytes));
    final bytes = ZipEncoder().encode(archive);
    if (bytes == null || bytes.length > maxFicha148Bytes) {
      throw const Ficha148ValidationException(['El paquete .ficha148 supera el límite permitido de 10 MB.'], packageError: true);
    }
    final folder = destino == null ? await getApplicationDocumentsDirectory() : Directory(File(destino).parent.path);
    final safeName = (documento['ficha']['nombre'] as String).replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_');
    final path = destino ?? '${folder.path}/$safeName.ficha148';
    return File(path).writeAsBytes(bytes, flush: true);
  }

  /// Validación completa con resumen, útil para pedir confirmación antes de importar.
  static Future<Ficha148ValidationSummary> validarArchivo(File archivo) async {
    final validator = await Ficha148Validator.desdeAssets();
    return validator.validarArchivo(archivo);
  }

  /// Compatibilidad con llamadas existentes; solo devuelve datos ya validados.
  static Future<Map<String, dynamic>> importar(File archivo) async =>
      (await validarArchivo(archivo)).document;
}
