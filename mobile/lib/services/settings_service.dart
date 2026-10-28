import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

class SettingsService {
  static const _keyBaseUrl = 'ai_base_url';
  static const _keyServerUrl = 'server_backend_url';
  static const _keyEvalConsent = 'evaluation_dataset_consent';
  static const _secureClientTokenKey = 'echo_client_token';
  static const _secureApiKey = 'echo_ai_api_key';

  final SharedPreferences _prefs;
  // Default Android options use AES-GCM with RSA key wrapping backed by the
  // Android Keystore. Never fall back to plain SharedPreferences for tokens.
  static const FlutterSecureStorage _secureStorage = FlutterSecureStorage();

  String _clientToken = '';
  String _apiKey = '';

  SettingsService(this._prefs);

  static Future<SettingsService> init() async {
    final prefs = await SharedPreferences.getInstance();
    final service = SettingsService(prefs);
    try {
      service._clientToken =
          await _secureStorage.read(key: _secureClientTokenKey) ?? '';
      service._apiKey = await _secureStorage.read(key: _secureApiKey) ?? '';
    } catch (_) {
      // A locked/unavailable keystore must not prevent the app from starting.
      service._clientToken = '';
      service._apiKey = '';
    }
    return service;
  }

  String get apiKey => _apiKey;
  Future<void> setApiKey(String value) async {
    _apiKey = value.trim();
    if (_apiKey.isEmpty) {
      await _secureStorage.delete(key: _secureApiKey);
    } else {
      await _secureStorage.write(key: _secureApiKey, value: _apiKey);
    }
  }

  String get baseUrl =>
      _prefs.getString(_keyBaseUrl) ?? 'https://api.openai.com/v1';
  set baseUrl(String value) => _prefs.setString(_keyBaseUrl, value);

  static const _keyModel = 'ai_model';
  String get model => _prefs.getString(_keyModel) ?? 'gpt-4o-mini';
  set model(String value) => _prefs.setString(_keyModel, value);

  /// Development default. On a physical phone this only works with
  /// `adb reverse tcp:8000 tcp:8000`; users can configure a LAN/HTTPS URL.
  String get serverUrl =>
      _prefs.getString(_keyServerUrl) ?? 'http://127.0.0.1:8000';
  set serverUrl(String value) => _prefs.setString(_keyServerUrl, value);

  String get clientToken => _clientToken;
  Future<void> setClientToken(String value) async {
    _clientToken = value.trim();
    if (_clientToken.isEmpty) {
      await _secureStorage.delete(key: _secureClientTokenKey);
    } else {
      await _secureStorage.write(
        key: _secureClientTokenKey,
        value: _clientToken,
      );
    }
  }

  // Evaluation consent: strictly default to FALSE (opt-in only)
  bool get evalConsent => _prefs.getBool(_keyEvalConsent) ?? false;
  set evalConsent(bool value) => _prefs.setBool(_keyEvalConsent, value);
}
