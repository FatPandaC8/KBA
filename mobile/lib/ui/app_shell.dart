import 'package:flutter/material.dart';

import 'package:mobile/services/audio_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';

import 'screens/detail/note_detail_screen.dart';
import 'screens/home/home_screen.dart';
import 'screens/library/library_screen.dart';
import 'screens/recall/recall_screen.dart';
import 'screens/settings/settings_screen.dart';
import 'widgets/echo_bottom_nav.dart';

class AppShell extends StatefulWidget {
  final NoteProvider noteProvider;
  final AudioService audioService;
  final SettingsService settingsService;

  const AppShell({
    super.key,
    required this.noteProvider,
    required this.audioService,
    required this.settingsService,
  });

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _currentTab = 0;
  String? _selectedNoteId;
  bool _isSettingsOpen = false;

  void _openDetail(String noteId) {
    setState(() {
      _selectedNoteId = noteId;
      _isSettingsOpen = false;
    });
  }

  void _closeDetail() {
    setState(() {
      _selectedNoteId = null;
    });
  }

  void _openSettings() {
    setState(() {
      _isSettingsOpen = true;
      _selectedNoteId = null;
    });
  }

  void _closeSettings() {
    setState(() {
      _isSettingsOpen = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_isSettingsOpen) {
      return SettingsScreen(
        settingsService: widget.settingsService,
        onBack: _closeSettings,
      );
    }

    if (_selectedNoteId != null) {
      return NoteDetailScreen(
        noteId: _selectedNoteId!,
        noteProvider: widget.noteProvider,
        onBack: _closeDetail,
      );
    }

    return Scaffold(
      body: IndexedStack(
        index: _currentTab,
        children: [
          HomeScreen(
            noteProvider: widget.noteProvider,
            audioService: widget.audioService,
            onOpenDetail: _openDetail,
            onOpenSettings: _openSettings,
            onOpenLibrary: () => setState(() => _currentTab = 2),
          ),
          RecallScreen(
            noteProvider: widget.noteProvider,
            onOpenDetail: _openDetail,
          ),
          LibraryScreen(
            noteProvider: widget.noteProvider,
            onOpenDetail: _openDetail,
            onOpenHome: () => setState(() => _currentTab = 0),
          ),
        ],
      ),
      bottomNavigationBar: EchoBottomNav(
        currentIndex: _currentTab,
        onTap: (index) {
          setState(() {
            _currentTab = index;
            _selectedNoteId = null;
            _isSettingsOpen = false;
          });
        },
      ),
    );
  }
}
