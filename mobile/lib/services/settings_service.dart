import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Persisted preferences and the authenticated session.
///
/// The service is a [ChangeNotifier] because the app shell must rebuild when a
/// session starts or ends: otherwise a successful sign-in would leave the user
/// on the auth gate until the next launch.
class SettingsService extends ChangeNotifier {
  static const _keyServerUrl = 'server_backend_url';
  static const _secureSessionTokenKey = 'echo_session_token';

  final SharedPreferences _prefs;
  // Default Android options use AES-GCM with RSA key wrapping backed by the
  // Android Keystore. Never fall back to plain SharedPreferences for tokens.
  static const FlutterSecureStorage _secureStorage = FlutterSecureStorage();

  String _sessionToken = '';

  SettingsService(this._prefs);

  static Future<SettingsService> init() async {
    final prefs = await SharedPreferences.getInstance();
    final service = SettingsService(prefs);
    try {
      service._sessionToken =
          await _secureStorage.read(key: _secureSessionTokenKey) ?? '';
    } catch (_) {
      // A locked/unavailable keystore must not prevent the app from starting.
      service._sessionToken = '';
    }
    return service;
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
    _persistSessionToken(_sessionToken);
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
    _persistSessionToken('');
    if (changed) notifyListeners();
  }

  /// Whether a session is currently established.
  bool get isAuthenticated => _sessionToken.isNotEmpty;

  /// Development default. On a physical phone this only works with
  /// `adb reverse tcp:8000 tcp:8000`; users can configure a LAN/HTTPS URL.
  String get serverUrl =>
      _prefs.getString(_keyServerUrl) ?? 'http://127.0.0.1:8000';
  set serverUrl(String value) => _prefs.setString(_keyServerUrl, value);
}
