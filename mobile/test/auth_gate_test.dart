import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/services/audio_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/app_shell.dart';
import 'package:mobile/ui/screens/home/home_screen.dart';
import 'package:mobile/ui/screens/settings/settings_screen.dart';

import 'support/fakes.dart';

class _IdleAudioService extends Fake implements AudioService {
  @override
  Future<bool> isRecording() async => false;
}

/// AUTH gate regression: a session change must switch the shell immediately.
/// Without this, a successful sign-in leaves the user stuck on Settings until
/// the next app launch.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('signing in and out moves between gate and tabs immediately', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final settings = SettingsService(prefs);
    final repo = FakeNoteRepository();
    final provider = NoteProvider(
      repo,
      FakeBackendService(settings),
      settings,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          noteProvider: provider,
          audioService: _IdleAudioService(),
          settingsService: settings,
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Signed out: only the auth gate is reachable.
    expect(find.byType(SettingsScreen), findsOneWidget);
    expect(find.byType(HomeScreen), findsNothing);

    await settings.setSessionToken('session-token-from-login');
    await tester.pumpAndSettle();

    // Signed in: the Record tab appears without a relaunch.
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.byType(SettingsScreen), findsNothing);

    await settings.clearSession();
    await tester.pumpAndSettle();

    // Signing out returns to the blocking gate.
    expect(find.byType(SettingsScreen), findsOneWidget);
    expect(find.byType(HomeScreen), findsNothing);
  });
}
