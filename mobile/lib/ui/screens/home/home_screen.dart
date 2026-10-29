import 'dart:async';

import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/audio_service.dart';
import 'package:mobile/state/note_provider.dart';

import 'package:mobile/ui/widgets/echo_app_bar.dart';
import 'package:mobile/ui/screens/home/widgets/mic_halo_button.dart';
import 'package:mobile/ui/screens/home/widgets/waveform_widget.dart';

class HomeScreen extends StatefulWidget {
  final NoteProvider noteProvider;
  final AudioService audioService;
  final Function(String noteId) onOpenDetail;
  final VoidCallback onOpenSettings;
  final VoidCallback onOpenLibrary;
  final ValueChanged<bool>? onRecordingStateChanged;

  const HomeScreen({
    super.key,
    required this.noteProvider,
    required this.audioService,
    required this.onOpenDetail,
    required this.onOpenSettings,
    required this.onOpenLibrary,
    this.onRecordingStateChanged,
  });

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  bool _isRecording = false;
  bool _isProcessing = false;
  int _recordSeconds = 0;
  Timer? _recordTimer;
  String? _errorMessage;
  DateTime? _recordingStartTime;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _recordTimer?.cancel();
    if (_isRecording) {
      widget.audioService.cancelRecording();
      widget.onRecordingStateChanged?.call(false);
    }
    super.dispose();
  }

  void _setRecording(bool value) {
    _isRecording = value;
    widget.onRecordingStateChanged?.call(value);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed && _isRecording) {
      _cancelRecording();
    }
  }

  static const int maxVoiceSeconds = 30;
  static const int minRecordingMs = 800; // minimum duration threshold

  void _startTimer() {
    _recordSeconds = 0;
    _recordTimer?.cancel();
    _recordTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (mounted) {
        setState(() {
          _recordSeconds++;
        });
        if (_recordSeconds >= maxVoiceSeconds) {
          _stopRecordingAndSubmit();
        }
      }
    });
  }

  void _stopTimer() {
    _recordTimer?.cancel();
    _recordSeconds = 0;
  }

  Future<void> _startRecording() async {
    if (_isRecording || _isProcessing) return;

    setState(() => _errorMessage = null);
    try {
      final hasPerm = await widget.audioService.checkPermission();
      if (!hasPerm) {
        final granted = await widget.audioService.requestPermission();
        if (!granted) {
          if (mounted) {
            setState(() {
              _errorMessage = 'Microphone permission was denied. Please allow mic access in system settings.';
            });
          }
          return;
        }
      }

      await widget.audioService.startRecording();
      _recordingStartTime = DateTime.now();
      _startTimer();
      if (mounted) {
        setState(() => _setRecording(true));
      }
    } catch (e) {
      if (mounted) {
        setState(() => _errorMessage = 'Microphone access failed: $e');
      }
    }
  }

  int _currentRecordDurationMs() {
    if (_recordingStartTime == null) return 0;
    final realElapsed = DateTime.now()
        .difference(_recordingStartTime!)
        .inMilliseconds;
    final timerElapsed = _recordSeconds * 1000;
    return realElapsed > timerElapsed ? realElapsed : timerElapsed;
  }

  Future<void> _stopRecordingAndSubmit() async {
    if (!_isRecording || _isProcessing) return;

    final durationMs = _currentRecordDurationMs();
    final elapsedSeconds = _recordSeconds;
    _stopTimer();
    _recordingStartTime = null;

    setState(() {
      _setRecording(false);
    });

    // Check if recording is below minimum threshold
    final isTooShort = durationMs < minRecordingMs && elapsedSeconds == 0;
    if (isTooShort) {
      await widget.audioService.cancelRecording();
      if (mounted) {
        setState(() {
          _errorMessage =
              'Recording too short. Hold the button while speaking.';
        });
      }
      return;
    }

    setState(() {
      _isProcessing = true;
      _errorMessage = null;
    });

    try {
      final result = await widget.audioService.stopRecording();
      if (result != null && mounted) {
        final note = await widget.noteProvider.createAudioNote(
          audioPath: result.path,
          durationMs: result.durationMs,
        );
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: const Text('Thought captured! Organizing…'),
              action: SnackBarAction(
                label: 'View',
                onPressed: () => widget.onOpenDetail(note.id),
              ),
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() => _errorMessage = e.toString());
      }
    } finally {
      if (mounted) {
        setState(() => _isProcessing = false);
      }
    }
  }

  Future<void> _cancelRecording() async {
    if (!_isRecording) return;
    _stopTimer();
    _recordingStartTime = null;
    setState(() => _setRecording(false));
    await widget.audioService.cancelRecording();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: EchoAppBar(title: 'Echo', onSettings: widget.onOpenSettings),
      body: ListenableBuilder(
        listenable: widget.noteProvider,
        builder: (context, _) {
          final recentNotes = widget.noteProvider.notes;
          final totalCount = recentNotes.length;

          return SafeArea(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final availableHeight = constraints.maxHeight;

                return CustomScrollView(
                  physics: const ClampingScrollPhysics(),
                  slivers: [
                    SliverFillRemaining(
                      hasScrollBody: false,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 20,
                          vertical: 8,
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            // Header
                            const Text(
                              'Capture what matters.',
                              style: TextStyle(
                                fontSize: 28,
                                fontWeight: FontWeight.w700,
                                color: EchoColors.ink,
                                letterSpacing: -0.8,
                              ),
                            ),
                            const SizedBox(height: 6),
                            Row(
                              children: [
                                Text(
                                  '$totalCount captures',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w600,
                                    color: EchoColors.ink,
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Container(
                                  width: 3,
                                  height: 3,
                                  decoration: const BoxDecoration(
                                    color: EchoColors.sage,
                                    shape: BoxShape.circle,
                                  ),
                                ),
                                const SizedBox(width: 8),
                                const Text(
                                  'Personal Knowledge',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: EchoColors.muted,
                                  ),
                                ),
                              ],
                            ),

                            // Flexible space above capture card (pushes button toward 70-80% of content area)
                            // On small screens, provides min 12px; on normal/tall screens, scales dynamically
                            const Spacer(flex: 3),

                            // Capture Zone
                            Container(
                              padding: EdgeInsets.symmetric(
                                vertical: availableHeight < 600 ? 16 : 28,
                                horizontal: 20,
                              ),
                              decoration: BoxDecoration(
                                color: Colors.white,
                                borderRadius: BorderRadius.circular(24),
                                border: Border.all(color: EchoColors.border),
                                boxShadow: const [
                                  BoxShadow(
                                    color: Color.fromRGBO(35, 42, 37, 0.04),
                                    blurRadius: 14,
                                    offset: Offset(0, 4),
                                  ),
                                ],
                              ),
                              child: Column(
                                children: [
                                  if (_isRecording) ...[
                                    const Row(
                                      mainAxisAlignment:
                                          MainAxisAlignment.center,
                                      children: [
                                        Icon(
                                          Icons.fiber_manual_record,
                                          color: EchoColors.danger,
                                          size: 14,
                                        ),
                                        SizedBox(width: 6),
                                        Text(
                                          'RECORDING',
                                          style: TextStyle(
                                            fontSize: 12,
                                            fontWeight: FontWeight.w700,
                                            color: EchoColors.danger,
                                            letterSpacing: 0.8,
                                          ),
                                        ),
                                      ],
                                    ),
                                    const SizedBox(height: 16),
                                    const WaveformWidget(isRecording: true),
                                    const SizedBox(height: 12),
                                    Text(
                                      '0:${_recordSeconds.toString().padLeft(2, '0')} / 0:$maxVoiceSeconds',
                                      style: const TextStyle(
                                        fontSize: 26,
                                        fontWeight: FontWeight.w600,
                                        fontFeatures: [
                                          FontFeature.tabularFigures(),
                                        ],
                                      ),
                                    ),
                                    const SizedBox(height: 24),
                                  ],

                                  MicHaloButton(
                                    isRecording: _isRecording,
                                    isProcessing: _isProcessing,
                                    onStartRecord: _startRecording,
                                    onStopRecord: _stopRecordingAndSubmit,
                                    onCancelRecord: _cancelRecording,
                                  ),
                                  const SizedBox(height: 20),
                                  Text(
                                    _isProcessing
                                        ? 'Organizing thoughts…'
                                        : (_isRecording
                                              ? 'Listening… Release to save'
                                              : 'Hold to talk · Release to save'),
                                    style: const TextStyle(
                                      fontSize: 18,
                                      fontWeight: FontWeight.w600,
                                      color: EchoColors.ink,
                                    ),
                                  ),
                                  const SizedBox(height: 6),
                                  Text(
                                    _isRecording
                                        ? 'Release anytime to finish recording.'
                                        : 'Your original capture is always safe.',
                                    style: const TextStyle(
                                      fontSize: 12,
                                      color: EchoColors.muted,
                                    ),
                                  ),

                                  if (_errorMessage != null) ...[
                                    const SizedBox(height: 12),
                                    Padding(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 20,
                                      ),
                                      child: Text(
                                        _errorMessage!,
                                        textAlign: TextAlign.center,
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: EchoColors.danger,
                                        ),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ),

                            // Bottom spacing: keeps enough space before the bottom nav bar
                            const SizedBox(height: 16),
                          ],
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          );
        },
      ),
    );
  }
}
