import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/data/models/note.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/screens/detail/widgets/audio_player_widget.dart';
import 'package:mobile/ui/screens/detail/widgets/delete_confirmation_dialog.dart';
import 'package:mobile/ui/widgets/echo_app_bar.dart';

/// My Recordings (VR-01/VR-03): date, duration, real status, playback,
/// owner-scoped deletion and manual retry. Transcripts are never shown.
class RecordingsScreen extends StatefulWidget {
  final NoteProvider noteProvider;
  final VoidCallback onBack;

  const RecordingsScreen({
    super.key,
    required this.noteProvider,
    required this.onBack,
  });

  @override
  State<RecordingsScreen> createState() => _RecordingsScreenState();
}

class _RecordingsScreenState extends State<RecordingsScreen> {
  String? _expandedId;
  String? _busyId;

  Future<void> _delete(Note note) async {
    await showDialog<void>(
      context: context,
      builder: (_) => DeleteConfirmationDialog(
        onConfirmDelete: () async {
          setState(() => _busyId = note.id);
          try {
            await widget.noteProvider.deleteNote(note.id);
          } catch (e) {
            if (!mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('Deletion failed. Nothing was removed: $e'),
              ),
            );
          } finally {
            if (mounted) setState(() => _busyId = null);
          }
        },
      ),
    );
  }

  Future<void> _retry(Note note) async {
    setState(() => _busyId = note.id);
    try {
      await widget.noteProvider.retryNote(note.id);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Retry failed: $e')));
    } finally {
      if (mounted) setState(() => _busyId = null);
    }
  }

  String _statusLabel(Note note) {
    if (note.status == ProcessingStatus.failed) {
      return 'Failed${note.errorClass.isNotEmpty ? ' · ${note.errorClass.replaceAll('_', ' ')}' : ''}';
    }
    switch (note.status) {
      case ProcessingStatus.queued:
        return 'Queued';
      case ProcessingStatus.uploading:
        return 'Uploading';
      case ProcessingStatus.pending:
        return 'Waiting for server';
      case ProcessingStatus.transcribing:
        return 'Transcribing';
      case ProcessingStatus.structuring:
        return 'Organizing ideas';
      case ProcessingStatus.ready:
        return 'Ready';
      case ProcessingStatus.rawOnly:
        return 'Saved on device';
      default:
        return 'Processing';
    }
  }

  String _formatDuration(int ms) {
    final seconds = (ms / 1000).round();
    final minutes = seconds ~/ 60;
    return '$minutes:${(seconds % 60).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.noteProvider,
      builder: (context, _) {
        final recordings = widget.noteProvider.notes;
        return Scaffold(
          appBar: EchoAppBar(title: 'My recordings', onBack: widget.onBack),
          body: SafeArea(
            child: recordings.isEmpty
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: Text(
                        'No recordings yet. Press and hold the microphone to capture a thought.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: EchoColors.muted, fontSize: 13),
                      ),
                    ),
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                    itemCount: recordings.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 12),
                    itemBuilder: (context, index) {
                      final note = recordings[index];
                      final expanded = _expandedId == note.id;
                      final failed = note.status == ProcessingStatus.failed;
                      final busy = _busyId == note.id;
                      final date = DateFormat('MMM d, yyyy · h:mm a')
                          .format(note.createdAt);

                      return Container(
                        decoration: BoxDecoration(
                          color: EchoColors.card,
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(
                            color: failed
                                ? EchoColors.danger
                                : EchoColors.border,
                          ),
                        ),
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        note.title,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(
                                          fontSize: 14,
                                          fontWeight: FontWeight.w700,
                                          color: EchoColors.ink,
                                        ),
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        '$date · ${_formatDuration(note.audioDurationMs ?? 0)}',
                                        style: const TextStyle(
                                          fontSize: 11,
                                          color: EchoColors.muted,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                if (note.canPlayAudio)
                                  IconButton(
                                    tooltip: expanded
                                        ? 'Hide audio player'
                                        : 'Play recording',
                                    icon: Icon(
                                      expanded
                                          ? Icons.expand_less
                                          : Icons.play_circle_outline,
                                      color: EchoColors.forest,
                                    ),
                                    onPressed: () => setState(
                                      () => _expandedId = expanded
                                          ? null
                                          : note.id,
                                    ),
                                  ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Row(
                              children: [
                                Icon(
                                  failed
                                      ? Icons.error_outline
                                      : (note.status == ProcessingStatus.ready
                                            ? Icons.check_circle_outline
                                            : Icons.sync),
                                  size: 14,
                                  color: failed
                                      ? EchoColors.danger
                                      : EchoColors.forest,
                                ),
                                const SizedBox(width: 6),
                                Expanded(
                                  child: Text(
                                    _statusLabel(note),
                                    style: TextStyle(
                                      fontSize: 11,
                                      fontWeight: FontWeight.w600,
                                      color: failed
                                          ? EchoColors.danger
                                          : EchoColors.forest,
                                    ),
                                  ),
                                ),
                                if (failed)
                                  TextButton.icon(
                                    onPressed: busy ? null : () => _retry(note),
                                    icon: const Icon(Icons.refresh, size: 14),
                                    label: const Text(
                                      'Retry',
                                      style: TextStyle(fontSize: 11),
                                    ),
                                  ),
                                IconButton(
                                  tooltip: 'Delete recording',
                                  onPressed: busy ? null : () => _delete(note),
                                  icon: const Icon(
                                    Icons.delete_outline,
                                    size: 18,
                                    color: EchoColors.danger,
                                  ),
                                ),
                              ],
                            ),
                            if (failed &&
                                note.failureReason != null &&
                                note.failureReason!.isNotEmpty) ...[
                              const SizedBox(height: 4),
                              Text(
                                note.failureReason!,
                                style: const TextStyle(
                                  fontSize: 11,
                                  height: 1.4,
                                  color: EchoColors.ink,
                                ),
                              ),
                            ],
                            if (expanded && note.canPlayAudio) ...[
                              const SizedBox(height: 10),
                              AudioPlayerWidget(
                                audioPath: note.hasLocalAudio
                                    ? note.audioPath
                                    : null,
                                durationMs: note.audioDurationMs,
                                remoteAudioLoader: note.hasLocalAudio
                                    ? null
                                    : () => widget.noteProvider.backendService
                                          .fetchAudioBytes(note.id),
                              ),
                            ],
                          ],
                        ),
                      );
                    },
                  ),
          ),
        );
      },
    );
  }
}
