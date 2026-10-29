import 'dart:convert';
import 'dart:io';

import 'package:ficha_costo_mobile/backup/backup_service.dart';
import 'package:ficha_costo_mobile/data/app_database.dart';
import 'package:ficha_costo_mobile/data/fichas_repository_sqlcipher.dart';
import 'package:ficha_costo_mobile/domain/models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('crea backup cifrado y restaura fichas, catálogos y preferencias en una DB vacía', () async {
    final directory = await Directory.systemTemp.createTemp('fichacosto-backup-test-');
    final source = AppDatabase(NativeDatabase.memory());
    final target = AppDatabase(NativeDatabase.memory());
    await source.inicializarLicencias();
    await target.inicializarLicencias();
    final repository = FichasRepositorySqlCipher(source);
    final ficha = FichaCosto(nombre: 'Mesa de prueba');
    await repository.guardar(ficha);
    await repository.guardarInsumo(Insumo(nombre: 'Madera', unidadMedida: 'm', costoUnitario: Importe(12.5, Moneda.CUP)));
    await repository.guardarTarifa(TarifaSalario(cargo: 'Carpintero', unidadTarifa: 'hora', tarifa: Importe(4, Moneda.CUP)));
    await source.customStatement('INSERT INTO preferences (key, value_json) VALUES (?, ?)', [Variable('tema'), Variable(jsonEncode('oscuro'))]);

    final backup = BackupService(source, fingerprintProvider: () async => 'a' * 64, outputDirectory: directory);
    final file = await backup.crearBackup('Correct Horse 2026');
    expect(file.path.endsWith('.ficha148.bak'), isTrue);
    final preview = await backup.previsualizarBackup(file, 'Correct Horse 2026');
    expect(preview.fichas, 1);
    expect(preview.insumos, 1);
    expect(preview.salarios, 1);
    expect(preview.origenDiferente, isFalse);

    final restore = BackupService(target, fingerprintProvider: () async => 'b' * 64, outputDirectory: directory);
    final movedPreview = await restore.previsualizarBackup(file, 'Correct Horse 2026');
    expect(movedPreview.origenDiferente, isTrue);
    await restore.aplicarRestauracion(movedPreview, modo: 'reemplazar', crearRespaldoSeguridad: false);
    final restored = await target.listarFichas();
    expect(restored, hasLength(1));
    expect(restored.single.documento, contains('Mesa de prueba'));
    final catalogItems = await target.listarCatalogo('insumo');
    final catalogSalary = await target.listarCatalogo('tarifa');
    expect(jsonDecode(catalogItems.single.documento)['nombre'], 'Madera');
    expect(jsonDecode(catalogSalary.single.documento)['cargo'], 'Carpintero');
    final preference = await target.customSelect('SELECT value_json FROM preferences WHERE key = ?', variables: [Variable('tema')]).getSingle();
    expect(jsonDecode(preference.read<String>('value_json')), 'oscuro');
    await source.close();
    await target.close();
    await directory.delete(recursive: true);
  });
}
