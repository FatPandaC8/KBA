import 'dart:async';

import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/core/theme/echo_theme.dart';
import 'package:mobile/services/audio_service.dart';
import 'package:mobile/state/note_provider.dart';

import 'package:mobile/ui/widgets/echo_app_bar.dart';
import 'package:mobile/ui/widgets/note_card.dart';
import 'package:mobile/ui/screens/home/widgets/mic_halo_button.dart';
import 'package:mobile/ui/screens/home/widgets/text_capture_dialog.dart';
import 'package:mobile/ui/screens/home/widgets/waveform_widget.dart';

class HomeScreen extends StatefulWidget {
  final NoteProvider noteProvider;
  final AudioService audioService;
  final Function(String noteId) onOpenDetail;
  final VoidCallback onOpenSettings;
  final VoidCallback onOpenLibrary;

  const HomeScreen({
    super.key,
    required this.noteProvider,
    required this.audioService,
    required this.onOpenDetail,
    required this.onOpenSettings,
    required this.onOpenLibrary,
  });

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  bool _isRecording = false;
  int _recordSeconds = 0;
  Timer? _recordTimer;
  String? _errorMessage;

  @override
  void dispose() {
    _recordTimer?.cancel();
    super.dispose();
  }

  static const int maxVoiceSeconds = 30;

  void _startTimer() {
    _recordSeconds = 0;
    _recordTimer?.cancel();
    _recordTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (mounted) {
        setState(() {
          _recordSeconds++;
        });
        if (_recordSeconds >= maxVoiceSeconds) {
          _toggleRecording();
        }
      }
    });
  }

  void _stopTimer() {
    _recordTimer?.cancel();
    _recordSeconds = 0;
  }

  Future<void> _toggleRecording() async {
    if (_isRecording) {
      // Stop recording
      _stopTimer();
      setState(() => _isRecording = false);
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
        setState(() => _errorMessage = e.toString());
      }
    } else {
      // Start recording
      setState(() => _errorMessage = null);
      try {
        await widget.audioService.startRecording();
        _startTimer();
        setState(() => _isRecording = true);
      } catch (e) {
        setState(
          () => _errorMessage = 'Microphone access needed or failed: $e',
        );
      }
    }
  }

  Future<void> _cancelRecording() async {
    _stopTimer();
    setState(() => _isRecording = false);
    await widget.audioService.cancelRecording();
  }

  void _openTextCapture() {
    showDialog(
      context: context,
      builder: (_) => TextCaptureDialog(
        onSave: (text) async {
          final note = await widget.noteProvider.createTextNote(text);
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: const Text('Thought saved!'),
                action: SnackBarAction(
                  label: 'Open',
                  onPressed: () => widget.onOpenDetail(note.id),
                ),
              ),
            );
          }
        },
      ),
    );
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
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Welcome Header
                  Text('YOUR KNOWLEDGE, GROWING.', style: EchoTheme.eyebrow),
                  const SizedBox(height: 6),
                  const Text(
                    'Capture what matters.',
                    style: TextStyle(
                      fontSize: 29,
                      fontWeight: FontWeight.w600,
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
                      Text(
                        'Local & Private',
                        style: TextStyle(fontSize: 12, color: EchoColors.muted),
                      ),
                    ],
                  ),
                  const SizedBox(height: 28),

                  // Capture Zone
                  Container(
                    padding: const EdgeInsets.symmetric(vertical: 24),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(24),
                      border: Border.all(color: EchoColors.border),
                    ),
                    child: Column(
                      children: [
                        if (_isRecording) ...[
                          const Row(
                            mainAxisAlignment: MainAxisAlignment.center,
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
                          const SizedBox(height: 12),
                          const WaveformWidget(isRecording: true),
                          const SizedBox(height: 8),
                          Text(
                            '0:${_recordSeconds.toString().padLeft(2, '0')} / 0:$maxVoiceSeconds',
                            style: const TextStyle(
                              fontSize: 24,
                              fontWeight: FontWeight.w600,
                              fontFeatures: [FontFeature.tabularFigures()],
                            ),
                          ),
                          const SizedBox(height: 18),
                        ],

                        MicHaloButton(
                          isRecording: _isRecording,
                          onTap: _toggleRecording,
                        ),
                        const SizedBox(height: 16),
                        Text(
                          _isRecording
                              ? 'Tap to finish recording'
                              : 'Tap mic to record audio',
                          style: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                            color: EchoColors.ink,
                          ),
                        ),
                        const SizedBox(height: 4),
                        const Text(
                          'Your original capture is always safe.',
                          style: TextStyle(
                            fontSize: 12,
                            color: EchoColors.muted,
                          ),
                        ),

                        if (_isRecording) ...[
                          const SizedBox(height: 14),
                          TextButton.icon(
                            icon: const Icon(
                              Icons.close,
                              size: 16,
                              color: EchoColors.danger,
                            ),
                            label: const Text(
                              'Cancel Recording',
                              style: TextStyle(color: EchoColors.danger),
                            ),
                            onPressed: _cancelRecording,
                          ),
                        ] else ...[
                          const SizedBox(height: 14),
                          OutlinedButton.icon(
                            icon: const Icon(
                              Icons.edit_note,
                              size: 18,
                              color: EchoColors.forest,
                            ),
                            label: const Text(
                              'Or type text note',
                              style: TextStyle(
                                fontWeight: FontWeight.w600,
                                color: EchoColors.forest,
                              ),
                            ),
                            style: OutlinedButton.styleFrom(
                              side: const BorderSide(color: EchoColors.sage),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                              padding: const EdgeInsets.symmetric(
                                horizontal: 16,
                                vertical: 10,
                              ),
                            ),
                            onPressed: _openTextCapture,
                          ),
                        ],

                        if (_errorMessage != null) ...[
                          const SizedBox(height: 12),
                          Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 20),
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

                  const SizedBox(height: 28),

                  // Recent Notes Section
                  if (recentNotes.isNotEmpty) ...[
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          'Recent',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: EchoColors.ink,
                          ),
                        ),
                        TextButton(
                          onPressed: widget.onOpenLibrary,
                          child: const Text(
                            'View all',
                            style: TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                              color: EchoColors.forest2,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    NoteCard(
                      note: recentNotes.first,
                      onTap: () => widget.onOpenDetail(recentNotes.first.id),
                      onRetry: () => widget.noteProvider.processNoteAI(
                        recentNotes.first.id,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}
