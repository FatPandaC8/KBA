import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persisted preferences and the authenticated session.
///
/// The service is a [ChangeNotifier] because the app shell must rebuild when a
/// session starts or ends: otherwise a successful sign-in would leave the user
/// on the auth gate until the next launch.
class SettingsService extends ChangeNotifier {
  /// Backend URL comes from build-time configuration (`--dart-define
  /// BACKEND_URL=...`), never from a user-editable setting. Debug builds default
  /// to the host dev backend (reachable via `adb reverse` or the emulator's
  /// `10.0.2.2`); release builds have no default and must be passed an explicit
  /// HTTPS URL, so no dev URL ever ships in a release binary.
  static const String backendUrl = String.fromEnvironment(
    'BACKEND_URL',
    defaultValue: kDebugMode ? 'http://127.0.0.1:8000' : '',
  );

  static const _secureSessionTokenKey = 'echo_session_token';

  // Default Android options use AES-GCM with RSA key wrapping backed by the
  // Android Keystore. Never fall back to plain SharedPreferences for tokens.
  static const FlutterSecureStorage _secureStorage = FlutterSecureStorage();

  String _sessionToken = '';

  SettingsService() {
    _loadSessionToken();
  }

  static Future<SettingsService> init() async {
    final service = SettingsService();
    return service;
  }

  Future<void> _loadSessionToken() async {
    try {
      _sessionToken = await _secureStorage.read(key: _secureSessionTokenKey) ?? '';
    } catch (_) {
      // A locked/unavailable keystore (or headless test VM) must not prevent
      // the app from starting.
      _sessionToken = '';
    }
  }

  /// The current bearer session token, or empty when not signed in.
  String get sessionToken => _sessionToken;

  /// Persist a session token obtained after sign-up or login.
  Future<void> setSessionToken(String value) async {
    final next = value.trim();
    final changed = next != _sessionToken;
    _sessionToken = next;
    // Persist to secure storage without blocking; a locked/unavailable
    // keystore (or headless test VM) must not prevent the app from running.
    await _persistSessionToken(_sessionToken);
    if (changed) notifyListeners();
  }

  Future<void> _persistSessionToken(String token) async {
    try {
      if (token.isEmpty) {
        await _secureStorage.delete(key: _secureSessionTokenKey);
      } else {
        await _secureStorage.write(
          key: _secureSessionTokenKey,
          value: token,
        );
      }
    } catch (_) {
      // In-memory token is still valid for this session.
    }
  }

  /// Clear the session token (logout / account deletion).
  Future<void> clearSession() async {
    final changed = _sessionToken.isNotEmpty;
    _sessionToken = '';
    await _persistSessionToken('');
    if (changed) notifyListeners();
  }

  /// Whether a session is currently established.
  bool get isAuthenticated => _sessionToken.isNotEmpty;

  /// Build-time backend URL. Users never see or edit it.
  String get serverUrl => backendUrl;
}
