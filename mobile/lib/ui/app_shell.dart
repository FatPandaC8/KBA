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
  final List<int> _tabHistory = [0];

  void _switchTab(int index) {
    if (_currentTab != index) {
      _currentTab = index;
      _tabHistory.add(index);
    }
    _selectedNoteId = null;
    _isSettingsOpen = false;
    setState(() {});
  }

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
    Widget activeScreen;
    String screenKey;

    if (_isSettingsOpen) {
      screenKey = 'settings';
      activeScreen = SettingsScreen(
        settingsService: widget.settingsService,
        onBack: _closeSettings,
      );
    } else if (_selectedNoteId != null) {
      screenKey = 'detail_$_selectedNoteId';
      activeScreen = NoteDetailScreen(
        noteId: _selectedNoteId!,
        noteProvider: widget.noteProvider,
        onBack: _closeDetail,
      );
    } else {
      screenKey = 'tab_$_currentTab';
      activeScreen = Scaffold(
        body: IndexedStack(
          index: _currentTab,
          children: [
            HomeScreen(
              noteProvider: widget.noteProvider,
              audioService: widget.audioService,
              onOpenDetail: _openDetail,
              onOpenSettings: _openSettings,
              onOpenLibrary: () => _switchTab(2),
            ),
            RecallScreen(
              noteProvider: widget.noteProvider,
              onOpenDetail: _openDetail,
            ),
            LibraryScreen(
              noteProvider: widget.noteProvider,
              onOpenDetail: _openDetail,
              onOpenHome: () => _switchTab(0),
            ),
          ],
        ),
        bottomNavigationBar: EchoBottomNav(
          currentIndex: _currentTab,
          onTap: (index) => _switchTab(index),
          onCenterCapture: () => _switchTab(0),
        ),
      );
    }

    final reduceMotion = MediaQuery.of(context).disableAnimations;

    return PopScope(
      canPop: !_canPopInternally,
      onPopInvokedWithResult: (didPop, result) {
        if (didPop) return;
        _handlePop();
      },
      child: AnimatedSwitcher(
        duration: reduceMotion ? Duration.zero : const Duration(milliseconds: 200),
        switchInCurve: Curves.easeOut,
        switchOutCurve: Curves.easeIn,
        child: KeyedSubtree(
          key: ValueKey(screenKey),
          child: activeScreen,
        ),
      ),
    );
  }
}
