import 'package:flutter/material.dart';

import 'core/theme/echo_theme.dart';
import 'data/repositories/note_repository.dart';
import 'services/ai_service.dart';
import 'services/audio_service.dart';
import 'services/backend_service.dart';
import 'services/settings_service.dart';
import 'state/note_provider.dart';
import 'ui/app_shell.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final settingsService = await SettingsService.init();
  final noteRepository = NoteRepository();
  final aiService = AIService(settingsService);
  final backendService = BackendService(settingsService);
  final noteProvider = NoteProvider(noteRepository, aiService, backendService);
  final audioService = AudioService();

  runApp(
    EchoApp(
      noteProvider: noteProvider,
      audioService: audioService,
      settingsService: settingsService,
    ),
  );
}

class EchoApp extends StatelessWidget {
  final NoteProvider noteProvider;
  final AudioService audioService;
  final SettingsService settingsService;

  const EchoApp({
    super.key,
    required this.noteProvider,
    required this.audioService,
    required this.settingsService,
  });

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Echo',
      debugShowCheckedModeBanner: false,
      theme: EchoTheme.lightTheme,
      home: AppShell(
        noteProvider: noteProvider,
        audioService: audioService,
        settingsService: settingsService,
      ),
    );
  }
}
