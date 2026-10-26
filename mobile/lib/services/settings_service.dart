import 'package:shared_preferences/shared_preferences.dart';

class SettingsService {
  static const _keyApiKey = 'ai_api_key';
  static const _keyBaseUrl = 'ai_base_url';
  static const _keyServerUrl = 'server_backend_url';
  static const _keyMaxVoiceSeconds = 'max_voice_seconds';
  static const _keyKeepAudio = 'keep_original_audio';
  static const _keyWifiOnly = 'wifi_only';
  static const _keyEvalConsent = 'evaluation_dataset_consent';

  final SharedPreferences _prefs;

  SettingsService(this._prefs);

  static Future<SettingsService> init() async {
    final prefs = await SharedPreferences.getInstance();
    return SettingsService(prefs);
  }

  String get apiKey => _prefs.getString(_keyApiKey) ?? '';
  set apiKey(String value) => _prefs.setString(_keyApiKey, value);

  String get baseUrl =>
      _prefs.getString(_keyBaseUrl) ?? 'https://api.openai.com/v1';
  set baseUrl(String value) => _prefs.setString(_keyBaseUrl, value);

  static const _keyModel = 'ai_model';
  String get model => _prefs.getString(_keyModel) ?? 'gpt-4o-mini';
  set model(String value) => _prefs.setString(_keyModel, value);

  String get serverUrl =>
      _prefs.getString(_keyServerUrl) ?? 'http://127.0.0.1:8000';
  set serverUrl(String value) => _prefs.setString(_keyServerUrl, value);

  int get maxVoiceSeconds => _prefs.getInt(_keyMaxVoiceSeconds) ?? 30;
  set maxVoiceSeconds(int value) => _prefs.setInt(_keyMaxVoiceSeconds, value);

  bool get keepAudio => _prefs.getBool(_keyKeepAudio) ?? true;
  set keepAudio(bool value) => _prefs.setBool(_keyKeepAudio, value);

  bool get wifiOnly => _prefs.getBool(_keyWifiOnly) ?? false;
  set wifiOnly(bool value) => _prefs.setBool(_keyWifiOnly, value);

  // Evaluation consent: strictly default to FALSE (opt-in only)
  bool get evalConsent => _prefs.getBool(_keyEvalConsent) ?? false;
  set evalConsent(bool value) => _prefs.setBool(_keyEvalConsent, value);
}

