import 'dart:async';

import 'package:flutter/material.dart';

import 'package:mobile/services/audio_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';

import 'screens/detail/note_detail_screen.dart';
import 'screens/home/home_screen.dart';
import 'screens/library/library_screen.dart';
import 'screens/settings/settings_screen.dart';
import 'screens/auth/welcome_screen.dart';
import 'widgets/echo_bottom_nav.dart';

/// Two tabs (PRD v2 navigation, Ask AI removed): Record (0), Graph (1).
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
  bool _isRecording = false;
  final List<int> _tabHistory = [0];

  @override
  void initState() {
    super.initState();
    widget.settingsService.addListener(_onSessionChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await widget.noteProvider.loadNotes();
      await widget.noteProvider.retryPendingWork();
    });
  }

  @override
  void didUpdateWidget(AppShell oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.settingsService != widget.settingsService) {
      oldWidget.settingsService.removeListener(_onSessionChanged);
      widget.settingsService.addListener(_onSessionChanged);
    }
  }

  /// Signing in or out must move the user between the auth gate and the tabs
  /// immediately, without a relaunch.
  void _onSessionChanged() {
    if (!mounted) return;
    // On logout, clear the local notes cache so nothing user-specific survives
    // in echo_notes.db (the token is already cleared by SettingsService).
    if (!widget.settingsService.isAuthenticated) {
      unawaited(widget.noteProvider.clearLocalNotes());
    }
    setState(() {
      _isSettingsOpen = false;
      _selectedNoteId = null;
      _currentTab = 0;
      _tabHistory
        ..clear()
        ..add(0);
    });
  }

  @override
  void dispose() {
    widget.settingsService.removeListener(_onSessionChanged);
    super.dispose();
  }

  void _showRecordingGuard() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Stop recording before leaving this screen.'),
      ),
    );
  }

  void _switchTab(int index) {
    if (_isRecording) {
      _showRecordingGuard();
      return;
    }
    if (_currentTab != index) {
      _currentTab = index;
      _tabHistory.add(index);
    }
    _selectedNoteId = null;
    _isSettingsOpen = false;
    setState(() {});
  }

  void _openDetail(String noteId) {
    if (_isRecording) {
      _showRecordingGuard();
      return;
    }
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
    if (_isRecording) {
      _showRecordingGuard();
      return;
    }
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

  bool get _canPopInternally =>
      _isSettingsOpen ||
      _selectedNoteId != null ||
      _tabHistory.length > 1 ||
      _currentTab != 0;

  void _handlePop() {
    if (_isSettingsOpen) {
      _closeSettings();
    } else if (_selectedNoteId != null) {
      _closeDetail();
    } else if (_tabHistory.length > 1) {
      _tabHistory.removeLast();
      setState(() {
        _currentTab = _tabHistory.last;
      });
    } else if (_currentTab != 0) {
      setState(() {
        _currentTab = 0;
        _tabHistory.clear();
        _tabHistory.add(0);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    // Logged-out users see only the welcoming auth experience.
    if (!widget.settingsService.isAuthenticated) {
      return WelcomeScreen(
        settingsService: widget.settingsService,
        backendService: widget.noteProvider.backendService,
      );
    }

    final tabScaffold = Scaffold(
      body: IndexedStack(
        index: _currentTab,
        children: [
          HomeScreen(
            noteProvider: widget.noteProvider,
            audioService: widget.audioService,
            onOpenDetail: _openDetail,
            onOpenSettings: _openSettings,
            onOpenLibrary: () => _switchTab(1),
            onOpenRecordings: () {},
            onRecordingStateChanged: (value) {
              if (_isRecording != value) {
                setState(() => _isRecording = value);
              }
            },
          ),
          LibraryScreen(noteProvider: widget.noteProvider),
        ],
      ),
      bottomNavigationBar: EchoBottomNav(
        currentIndex: _currentTab,
        onTap: (index) => _switchTab(index),
      ),
    );

    return PopScope(
      canPop: !_canPopInternally,
      onPopInvokedWithResult: (didPop, result) {
        if (didPop) return;
        _handlePop();
      },
      child: Stack(
        children: [
          // Kept mounted at all times so tab/search/filter state survives
          // navigation and detail/settings overlays.
          tabScaffold,
          if (_selectedNoteId != null)
            Positioned.fill(
              child: NoteDetailScreen(
                noteId: _selectedNoteId!,
                noteProvider: widget.noteProvider,
                onBack: _closeDetail,
              ),
            ),
          if (_isSettingsOpen)
            Positioned.fill(
              child: SettingsScreen(
                settingsService: widget.settingsService,
                backendService: widget.noteProvider.backendService,
                onBack: _closeSettings,
              ),
            ),
        ],
      ),
    );
  }
}
