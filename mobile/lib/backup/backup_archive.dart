import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';

const String backupRoot = 'ficha148_backup_v1/';
const String backupManifestEntry = '${backupRoot}manifest.json';
const String backupPayloadEntry = '${backupRoot}payload.enc';
const int maxBackupArchiveBytes = 160 * 1024 * 1024;
const int maxBackupManifestBytes = 32 * 1024;
const int maxBackupCiphertextBytes = 128 * 1024 * 1024;

class BackupArchiveException implements Exception {
  const BackupArchiveException(this.message);
  final String message;
  @override String toString() => message;
}

class BackupArchiveContents {
  const BackupArchiveContents(this.manifestBytes, this.ciphertext);
  final Uint8List manifestBytes;
  final Uint8List ciphertext;
}

Uint8List buildBackupZip(List<int> manifest, List<int> ciphertext) {
  if (manifest.length > maxBackupManifestBytes || ciphertext.length > maxBackupCiphertextBytes) {
    throw const BackupArchiveException('El respaldo supera el tamaño máximo permitido.');
  }
  final archive = Archive();
  archive.addFile(ArchiveFile(backupManifestEntry, manifest.length, manifest)..compression = CompressionType.none);
  archive.addFile(ArchiveFile(backupPayloadEntry, ciphertext.length, ciphertext)..compression = CompressionType.none);
  final result = ZipEncoder().encode(archive, level: 0);
  if (result == null || result.length > maxBackupArchiveBytes) {
    throw const BackupArchiveException('No se pudo empaquetar el respaldo dentro del límite permitido.');
  }
  return Uint8List.fromList(result);
}

Future<BackupArchiveContents> readBackupZip(File file) async {
  try {
    final length = await file.length();
    if (length < 4 || length > maxBackupArchiveBytes) throw const BackupArchiveException('El archivo de respaldo supera el tamaño permitido o está vacío.');
    final bytes = await file.openRead(0, maxBackupArchiveBytes + 1).fold<List<int>>(<int>[], (all, chunk) {
      all.addAll(chunk);
      return all;
    });
    if (bytes.length > maxBackupArchiveBytes) throw const BackupArchiveException('El archivo de respaldo supera el tamaño permitido.');
    final archive = ZipDecoder().decodeBytes(bytes, verify: false);
    final expected = {backupManifestEntry, backupPayloadEntry};
    if (archive.files.length != expected.length) throw const BackupArchiveException('El ZIP no contiene exactamente los archivos del respaldo v1.');
    final found = <String, Uint8List>{};
    for (final entry in archive.files) {
      _checkName(entry.name);
      if (!entry.isFile || entry.isSymbolicLink || !expected.contains(entry.name) || found.containsKey(entry.name)) {
        throw const BackupArchiveException('El ZIP contiene entradas no permitidas o duplicadas.');
      }
      // Backup ZIP members are intentionally stored, never deflated. The payload
      // already uses gzip before encryption; this also prevents ZIP bombs.
      if (entry.compression != CompressionType.none) {
        throw const BackupArchiveException('El ZIP usa una compresión no admitida. Vuelva a crear el respaldo con FichaCosto.');
      }
      final limit = entry.name == backupManifestEntry ? maxBackupManifestBytes : maxBackupCiphertextBytes;
      if (entry.size < 0 || entry.size > limit) throw const BackupArchiveException('Una entrada ZIP supera el tamaño permitido.');
      final bytesValue = _readBounded(entry, limit);
      if (bytesValue.length != entry.size || (entry.crc32 != null && getCrc32(bytesValue) != entry.crc32)) {
        throw const BackupArchiveException('Una entrada ZIP está dañada.');
      }
      found[entry.name] = bytesValue;
    }
    if (!found.keys.toSet().containsAll(expected)) throw const BackupArchiveException('Falta una entrada obligatoria del respaldo.');
    return BackupArchiveContents(found[backupManifestEntry]!, found[backupPayloadEntry]!);
  } on BackupArchiveException {
    rethrow;
  } catch (_) {
    throw const BackupArchiveException('El archivo no es un ZIP de respaldo válido o está dañado.');
  }
}

Uint8List _readBounded(ArchiveFile entry, int maxBytes) {
  final stream = entry.getContent();
  if (stream == null) throw const BackupArchiveException('No se pudo leer una entrada del ZIP.');
  final builder = BytesBuilder(copy: false);
  var total = 0;
  while (!stream.isEOS) {
    final count = stream.length < 64 * 1024 ? stream.length : 64 * 1024;
    if (count <= 0) throw const BackupArchiveException('El ZIP contiene un flujo inválido.');
    final chunk = stream.readBytes(count).toUint8List();
    total += chunk.length;
    if (chunk.isEmpty || total > maxBytes) throw const BackupArchiveException('Una entrada ZIP excede el tamaño permitido.');
    builder.add(chunk);
  }
  return builder.takeBytes();
}

void _checkName(String name) {
  final pieces = name.split('/');
  if (name.isEmpty || name.startsWith('/') || name.contains('\\') || name.contains(':') ||
      pieces.any((part) => part.isEmpty || part == '.' || part == '..')) {
    throw const BackupArchiveException('El ZIP contiene una ruta no segura.');
  }
}
