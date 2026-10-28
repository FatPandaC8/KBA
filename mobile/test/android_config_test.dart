import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Android manifest identifies Echo and requests microphone access', () {
    final manifest = File('android/app/src/main/AndroidManifest.xml')
        .readAsStringSync();

    expect(manifest, contains('android:label="Echo"'));
    expect(manifest, contains('android.permission.RECORD_AUDIO'));
    expect(manifest, contains('android.permission.INTERNET'));
    expect(manifest, isNot(contains('android:label="mobile"')));
  });

  test('debug builds allow local cleartext HTTP without weakening release', () {
    final debugManifest = File('android/app/src/debug/AndroidManifest.xml')
        .readAsStringSync();
    final mainManifest = File('android/app/src/main/AndroidManifest.xml')
        .readAsStringSync();

    expect(debugManifest, contains('android:usesCleartextTraffic="true"'));
    expect(mainManifest, isNot(contains('usesCleartextTraffic')));
  });

  test('release signing requires owner keystore configuration', () {
    final gradle = File('android/app/build.gradle.kts').readAsStringSync();

    expect(gradle, contains('applicationId = "dev.echo.notes.dev"'));
    expect(gradle, contains('keystorePropertiesFile.exists()'));
    expect(gradle, contains('signingConfigs.getByName("release")'));
    expect(gradle, contains('signingConfigs.getByName("debug")'));
    // Release uses the debug key only when no owner keystore is configured.
    expect(
      gradle,
      contains('signingConfig = if (keystorePropertiesFile.exists())'),
    );
  });
}
