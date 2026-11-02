import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/data/models/note.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/widgets/echo_app_bar.dart';
import 'package:mobile/ui/screens/detail/widgets/audio_player_widget.dart';
import 'package:mobile/ui/screens/detail/widgets/delete_confirmation_dialog.dart';

class NoteDetailScreen extends StatefulWidget {
  final String noteId;
  final NoteProvider noteProvider;
  final VoidCallback onBack;

  const NoteDetailScreen({
    super.key,
    required this.noteId,
    required this.noteProvider,
    required this.onBack,
  });

  @override
  State<NoteDetailScreen> createState() => _NoteDetailScreenState();
}

class _NoteDetailScreenState extends State<NoteDetailScreen> {
  bool _isEditing = false;
  late TextEditingController _titleController;
  late TextEditingController _summaryController;

  @override
  void initState() {
    super.initState();
    final note = _getNote();
    _titleController = TextEditingController(text: note?.title ?? '');
    _summaryController = TextEditingController(text: note?.summary ?? '');
    widget.noteProvider.addListener(_onProviderChanged);
  }

  @override
  void dispose() {
    widget.noteProvider.removeListener(_onProviderChanged);
    _titleController.dispose();
    _summaryController.dispose();
    super.dispose();
  }

  /// Keeps the display controllers aligned with the latest stored note while
  /// the user is not editing. This prevents an in-flight AI result from being
  /// silently replaced by stale text when editing starts later.
  void _onProviderChanged() {
    if (!mounted || _isEditing) return;
    final note = _getNote();
    if (note == null) return;
    _syncControllers(note);
  }

  void _syncControllers(Note note) {
    _titleController.text = note.title;
    _summaryController.text = note.summary ?? '';
  }

  void _beginEditing() {
    final note = _getNote();
    if (note == null) return;
    _syncControllers(note);
    setState(() => _isEditing = true);
  }

  Note? _getNote() {
    try {
      return widget.noteProvider.notes.firstWhere((n) => n.id == widget.noteId);
    } catch (_) {
      return null;
    }
  }

  Future<void> _saveEdits() async {
    final note = _getNote();
    if (note == null) return;
    final updated = note.copyWith(
      title: _titleController.text.trim().isEmpty
          ? note.title
          : _titleController.text.trim(),
      summary: _summaryController.text.trim(),
    );
    setState(() => _isEditing = false);
    try {
      await widget.noteProvider.updateNote(updated);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Could not save changes: $e')));
    }
  }

  Future<void> _confirmDelete() async {
    await showDialog<void>(
      context: context,
      builder: (_) => DeleteConfirmationDialog(
        onConfirmDelete: () async {
          try {
            await widget.noteProvider.deleteNote(widget.noteId);
            if (!mounted) return;
            widget.onBack();
          } catch (e) {
            if (!mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('Deletion failed. Nothing was removed: $e'),
              ),
            );
          }
        },
      ),
    );
  }

  Future<void> _retry(Note note) async {
    try {
      await widget.noteProvider.retryNote(note.id);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Retry failed: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.noteProvider,
      builder: (context, _) {
        final note = _getNote();
        if (note == null) {
          return Scaffold(
            appBar: EchoAppBar(title: 'Note', onBack: widget.onBack),
            body: const Center(child: Text('Note not found or deleted.')),
          );
        }

        final dateFormat = DateFormat('MMMM d, yyyy · h:mm a');
        final dateStr = dateFormat.format(note.createdAt);

        return Scaffold(
          appBar: EchoAppBar(title: 'Knowledge item', onBack: widget.onBack),
          body: SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Title Row
                  if (_isEditing)
                    TextField(
                      controller: _titleController,
                      style: const TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w700,
                        color: EchoColors.ink,
                      ),
                      decoration: const InputDecoration(
                        border: UnderlineInputBorder(
                          borderSide: BorderSide(color: EchoColors.forest),
                        ),
                        contentPadding: EdgeInsets.zero,
                      ),
                    )
                  else
                    Text(
                      note.title,
                      style: const TextStyle(
                        fontSize: 26,
                        fontWeight: FontWeight.w700,
                        color: EchoColors.ink,
                        letterSpacing: -0.5,
                      ),
                    ),
                  const SizedBox(height: 6),
                  Text(
                    'Captured $dateStr',
                    style: const TextStyle(
                      fontSize: 11,
                      color: EchoColors.muted,
                    ),
                  ),
                  const SizedBox(height: 18),

                  if (note.failureReason != null &&
                      note.failureReason!.isNotEmpty) ...[
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: EchoColors.dangerSoft,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: EchoColors.danger),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'Processing did not finish',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              color: EchoColors.danger,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            note.failureReason!,
                            style: const TextStyle(
                              fontSize: 11,
                              height: 1.4,
                              color: EchoColors.ink,
                            ),
                          ),
                          // Pipeline split (S2): retries are always manual
                          // (no attempt budget), so nothing is shown here.
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  // Audio Player. The split pipeline (S4b) stores no audio
                  // server-side, so only the local copy can be played.
                  if (note.hasLocalAudio) ...[
                    AudioPlayerWidget(
                      audioPath: note.audioPath,
                      durationMs: note.audioDurationMs,
                    ),
                    const SizedBox(height: 16),
                  ],

                  // AI-Derived Section matching Figma
                  if (note.summary != null ||
                      note.keyFacts.isNotEmpty ||
                      _isEditing) ...[
                    Container(
                      decoration: BoxDecoration(
                        color: const Color(0xFFF1F4EF),
                        borderRadius: BorderRadius.circular(18),
                        border: Border.all(color: const Color(0xFFD8E0D5)),
                      ),
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              const Row(
                                children: [
                                  Icon(
                                    Icons.auto_awesome,
                                    size: 16,
                                    color: EchoColors.forest,
                                  ),
                                  SizedBox(width: 6),
                                  Text(
                                    'ORGANIZED IDEAS',
                                    style: TextStyle(
                                      fontSize: 10,
                                      fontWeight: FontWeight.w700,
                                      letterSpacing: 1.0,
                                      color: EchoColors.forest,
                                    ),
                                  ),
                                ],
                              ),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 6,
                                  vertical: 3,
                                ),
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(8),
                                  border: Border.all(
                                    color: const Color(0xFFD3D8D0),
                                  ),
                                ),
                                child: const Text(
                                  'AI-DERIVED',
                                  style: TextStyle(
                                    fontSize: 8,
                                    color: EchoColors.muted,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),
                          if (_isEditing)
                            TextField(
                              controller: _summaryController,
                              maxLines: 4,
                              style: const TextStyle(
                                fontSize: 13,
                                height: 1.5,
                                color: EchoColors.ink,
                              ),
                              decoration: InputDecoration(
                                filled: true,
                                fillColor: Colors.white,
                                border: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(10),
                                ),
                              ),
                            )
                          else if (note.summary != null)
                            Text(
                              note.summary!,
                              style: const TextStyle(
                                fontSize: 13,
                                height: 1.55,
                                color: Color(0xFF454A45),
                              ),
                            ),

                          // Key Facts
                          if (note.keyFacts.isNotEmpty) ...[
                            const SizedBox(height: 14),
                            const Text(
                              'Key facts',
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                                color: EchoColors.ink,
                              ),
                            ),
                            const SizedBox(height: 6),
                            ...note.keyFacts.map(
                              (fact) => Padding(
                                padding: const EdgeInsets.only(bottom: 4),
                                child: Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    const Text(
                                      '• ',
                                      style: TextStyle(
                                        color: EchoColors.forest,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                    Expanded(
                                      child: Text(
                                        fact,
                                        style: const TextStyle(
                                          fontSize: 12,
                                          height: 1.45,
                                          color: Color(0xFF454A45),
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  // Preservation Note matching Figma
                  Container(
                    margin: const EdgeInsets.symmetric(vertical: 18),
                    padding: const EdgeInsets.only(left: 10),
                    decoration: const BoxDecoration(
                      border: Border(
                        left: BorderSide(color: EchoColors.sage, width: 2),
                      ),
                    ),
                    child: const Text(
                      'Changes to organized ideas never alter your original recording.',
                      style: TextStyle(
                        fontSize: 11,
                        color: EchoColors.muted,
                        height: 1.4,
                      ),
                    ),
                  ),

                  // Actions
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (_isEditing)
                        ElevatedButton.icon(
                          style: ElevatedButton.styleFrom(
                            backgroundColor: EchoColors.forest,
                            foregroundColor: Colors.white,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(14),
                            ),
                            padding: const EdgeInsets.symmetric(vertical: 14),
                            elevation: 0,
                          ),
                          icon: const Icon(Icons.check, size: 18),
                          label: const Text(
                            'Save changes',
                            style: TextStyle(fontWeight: FontWeight.w600),
                          ),
                          onPressed: _saveEdits,
                        )
                      else ...[
                        OutlinedButton.icon(
                          style: OutlinedButton.styleFrom(
                            foregroundColor: EchoColors.forest,
                            side: const BorderSide(color: Color(0xFFBFC8BD)),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(14),
                            ),
                            padding: const EdgeInsets.symmetric(vertical: 14),
                          ),
                          icon: const Icon(Icons.edit_outlined, size: 18),
                          label: const Text(
                            'Edit organized ideas',
                            style: TextStyle(fontWeight: FontWeight.w600),
                          ),
                          onPressed: _beginEditing,
                        ),
                        if (note.status == ProcessingStatus.failed ||
                            note.status == ProcessingStatus.rawOnly) ...[
                          const SizedBox(height: 8),
                          ElevatedButton.icon(
                            style: ElevatedButton.styleFrom(
                              backgroundColor: EchoColors.forest,
                              foregroundColor: Colors.white,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(14),
                              ),
                              padding: const EdgeInsets.symmetric(vertical: 14),
                              elevation: 0,
                            ),
                            icon: const Icon(Icons.refresh, size: 18),
                            label: const Text(
                              'Retry processing',
                              style: TextStyle(fontWeight: FontWeight.w600),
                            ),
                            onPressed: () => _retry(note),
                          ),
                        ],
                      ],
                      const SizedBox(height: 8),
                      TextButton.icon(
                        style: TextButton.styleFrom(
                          foregroundColor: EchoColors.danger,
                          padding: const EdgeInsets.symmetric(vertical: 12),
                        ),
                        icon: const Icon(Icons.delete_outline, size: 18),
                        label: const Text(
                          'Delete',
                          style: TextStyle(fontWeight: FontWeight.w600),
                        ),
                        onPressed: _confirmDelete,
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
