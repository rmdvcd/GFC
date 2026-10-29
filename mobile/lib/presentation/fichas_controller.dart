import 'package:flutter/foundation.dart';
import '../data/fichas_repository_sqlcipher.dart';
import '../domain/models.dart';

class FichasController extends ChangeNotifier {
  FichasController(this.repository);
  final FichasRepositorySqlCipher repository;
  List<FichaCosto> fichas = [];
  bool cargando = false;
  String? error;

  Future<void> cargar() async {
    cargando = true; error = null; notifyListeners();
    try { fichas = await repository.listar(); } catch (e) { error = e.toString(); }
    cargando = false; notifyListeners();
  }
  Future<void> guardar(FichaCosto ficha) async { await repository.guardar(ficha); await cargar(); }
  Future<void> eliminar(String id) async { await repository.eliminar(id); await cargar(); }
}
