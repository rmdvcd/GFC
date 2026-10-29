import 'package:drift/native.dart';
import 'package:ficha_costo_mobile/data/app_database.dart';
import 'package:ficha_costo_mobile/help/help_service.dart';
import 'package:ficha_costo_mobile/help/help_widgets.dart';
import 'package:ficha_costo_mobile/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late AppDatabase db;
  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    await db.inicializarLicencias();
  });
  tearDown(() async => db.close());

  testWidgets('el onboarding aparece en la primera ejecución y se omite tras completarlo', (tester) async {
    final help = await HelpService.load(db);
    expect(await help.onboardingCompletado, isFalse);
    await tester.pumpWidget(ProviderScope(child: MaterialApp(home: HelpStartup(database: db))));
    await tester.pumpAndSettle();
    expect(find.text('Bienvenido a FichaCosto'), findsOneWidget);

    await help.marcarOnboardingCompletado();
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpWidget(ProviderScope(child: MaterialApp(home: HelpStartup(database: db))));
    await tester.pumpAndSettle();
    expect(find.text('Bienvenido a FichaCosto'), findsNothing);
    expect(find.text('FichaCosto'), findsOneWidget);
  });

  testWidgets('el icono de ayuda abre el contenido contextual desde JSON', (tester) async {
    final help = await HelpService.load(db);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: HelpTooltip(service: help, id: 'campo_fila_1'))));
    await tester.tap(find.byTooltip('Fila 1 · Materias primas y materiales. Abrir explicación'));
    await tester.pumpAndSettle();
    expect(find.text('Fila 1 · Materias primas y materiales'), findsOneWidget);
    expect(find.textContaining('carta tecnológica'), findsOneWidget);
  });
}
