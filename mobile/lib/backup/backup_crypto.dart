import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:unorm_dart/unorm_dart.dart' as unorm;

const int backupKdfIterations = 3;
const int backupKdfParallelism = 4;
const int backupDefaultMemoryKiB = 65536;
const int backupFallbackMemoryKiB = 32768;
const int backupSaltBytes = 16;
const int backupNonceBytes = 12;
const int backupTagBytes = 16;

class DerivedBackupKey {
  const DerivedBackupKey(this.bytes, this.memoryKiB);
  final List<int> bytes;
  final int memoryKiB;
}

class BackupAuthenticationException implements Exception {
  const BackupAuthenticationException();
}

/// RFC 9106 Argon2id parameters are recorded in the clear manifest (memory is KiB).
/// Passwords are normalized to NFC and encoded as UTF-8 on both platforms.
Future<DerivedBackupKey> deriveBackupKey(String password, List<int> salt, {int memoryKiB = backupDefaultMemoryKiB, bool allowFallback = true}) async {
  final passwordBytes = utf8.encode(unorm.nfc(password));
  Future<List<int>> calculate(int memory) async {
    final kdf = Argon2id(memory: memory, iterations: backupKdfIterations,
        parallelism: backupKdfParallelism, hashLength: 32);
    final secret = await kdf.deriveKey(secretKey: SecretKey(passwordBytes), nonce: salt);
    return secret.extractBytes();
  }
  try {
    return DerivedBackupKey(await calculate(memoryKiB), memoryKiB);
  } catch (error) {
    if (memoryKiB != backupDefaultMemoryKiB || !allowFallback) rethrow;
    // Android devices with limited memory get a recorded 32 MiB KDF profile.
    try {
      return DerivedBackupKey(await calculate(backupFallbackMemoryKiB), backupFallbackMemoryKiB);
    } catch (_) {
      rethrow;
    }
  }
}

/// AES-GCM returns ciphertext and tag separately; the shared ZIP format stores
/// ciphertext followed by the 16-byte tag, matching Python cryptography.AESGCM.
Future<List<int>> encryptBackup(List<int> key, List<int> nonce, List<int> aad, List<int> plaintext) async {
  final box = await AesGcm.with256bits().encrypt(plaintext,
      secretKey: SecretKey(key), nonce: nonce, aad: aad);
  return <int>[...box.cipherText, ...box.mac.bytes];
}

Future<List<int>> decryptBackup(List<int> key, List<int> nonce, List<int> aad, List<int> ciphertextAndTag) async {
  if (key.length != 32 || nonce.length != backupNonceBytes || ciphertextAndTag.length < backupTagBytes) {
    throw const BackupAuthenticationException();
  }
  final split = ciphertextAndTag.length - backupTagBytes;
  final box = SecretBox(ciphertextAndTag.sublist(0, split), nonce: nonce,
      mac: Mac(ciphertextAndTag.sublist(split)));
  try {
    return await AesGcm.with256bits().decrypt(box, secretKey: SecretKey(key), aad: aad);
  } on SecretBoxAuthenticationError {
    // GCM cannot distinguish a wrong password from authenticated-data tampering.
    throw const BackupAuthenticationException();
  }
}
