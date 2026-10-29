enum EstadoLicencia {
  valida('VALIDA'),
  expirada('EXPIRADA'),
  fingerprintNoCoincide('FINGERPRINT_NO_COINCIDE'),
  firmaInvalida('FIRMA_INVALIDA'),
  schemaInvalido('SCHEMA_INVALIDO'),
  noInstalada('NO_INSTALADA');

  const EstadoLicencia(this.codigo);
  final String codigo;
}

class ResultadoLicencia {
  const ResultadoLicencia(this.estado, {this.payload, this.motivoRechazo, this.advertencia});
  final EstadoLicencia estado;
  final Map<String, dynamic>? payload;
  final String? motivoRechazo;
  final String? advertencia;
  bool get valida => estado == EstadoLicencia.valida;
}

class EstadoLicenciaActual extends ResultadoLicencia {
  const EstadoLicenciaActual(super.estado, {
    super.payload,
    super.motivoRechazo,
    super.advertencia,
    this.tipo,
    this.features = const [],
    this.fichasRestantes,
    this.diasHastaExpiracion,
  });
  final String? tipo;
  final List<String> features;
  final int? fichasRestantes;
  final int? diasHastaExpiracion;

  // El acceso de lectura no se revoca por licenciamiento. PDF se conserva siempre;
  // en estado no premium se genera con marca de agua.
  bool get permiteLectura => true;
  bool get pdfConMarcaAgua => estado != EstadoLicencia.valida || !features.contains('pdf');
}
