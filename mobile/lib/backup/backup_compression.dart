import 'dart:io';
import 'dart:typed_data';

const int maxBackupPlaintextBytes = 256 * 1024 * 1024;

Uint8List gzipBackup(List<int> jsonBytes) => Uint8List.fromList(gzip.encode(jsonBytes, level: 6));

Future<Uint8List> gunzipBackupBounded(List<int> compressed) async {
  final builder = BytesBuilder(copy: false);
  var length = 0;
  try {
    await for (final chunk in Stream<List<int>>.value(compressed).transform(gzip.decoder)) {
      length += chunk.length;
      if (length > maxBackupPlaintextBytes) {
        throw const FormatException('El contenido descomprimido supera el límite permitido.');
      }
      builder.add(chunk);
    }
  } on FormatException {
    rethrow;
  } catch (_) {
    throw const FormatException('El contenido gzip está dañado.');
  }
  return builder.takeBytes();
}
