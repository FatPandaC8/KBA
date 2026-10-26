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
  late TextEditingController _originalController;

  @override
  void initState() {
    super.initState();
    final note = _getNote();
    _titleController = TextEditingController(text: note?.title ?? '');
    _summaryController = TextEditingController(text: note?.summary ?? '');
    _originalController = TextEditingController(
      text: note?.originalContent ?? '',
    );
  }

  @override
  void dispose() {
    _titleController.dispose();
    _summaryController.dispose();
    _originalController.dispose();
    super.dispose();
  }

  Note? _getNote() {
    try {
      return widget.noteProvider.notes.firstWhere((n) => n.id == widget.noteId);
    } catch (_) {
      return null;
    }
  }

  void _saveEdits() {
    final note = _getNote();
    if (note != null) {
      final updated = note.copyWith(
        title: _titleController.text.trim(),
        summary: _summaryController.text.trim(),
        originalContent: _originalController.text.trim(),
      );
      widget.noteProvider.updateNote(updated);
    }
    setState(() => _isEditing = false);
  }

  void _confirmDelete() {
    showDialog(
      context: context,
      builder: (_) => DeleteConfirmationDialog(
        onConfirmDelete: () async {
          await widget.noteProvider.deleteNote(widget.noteId);
          widget.onBack();
        },
      ),
    );
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

                  // Audio Player if audio note
                  if (note.audioPath != null && note.audioPath!.isNotEmpty) ...[
                    AudioPlayerWidget(
                      audioPath: note.audioPath!,
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

                  // Original Content / Transcript Section
                  Container(
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: EchoColors.border),
                    ),
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              note.audioPath != null
                                  ? 'ORIGINAL TRANSCRIPT'
                                  : 'ORIGINAL CAPTURE',
                              style: const TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w700,
                                letterSpacing: 1.0,
                                color: EchoColors.forest,
                              ),
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
                                'PRESERVED',
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
                        if (_isEditing && note.audioPath == null)
                          TextField(
                            controller: _originalController,
                            maxLines: 4,
                            style: const TextStyle(
                              fontSize: 13,
                              height: 1.5,
                              color: EchoColors.ink,
                            ),
                            decoration: InputDecoration(
                              filled: true,
                              fillColor: EchoColors.surface,
                              border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(10),
                              ),
                            ),
                          )
                        else
                          Text(
                            note.transcript?.isNotEmpty == true
                                ? note.transcript!
                                : note.originalContent,
                            style: const TextStyle(
                              fontSize: 13,
                              height: 1.55,
                              color: Color(0xFF454A45),
                            ),
                          ),
                      ],
                    ),
                  ),

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
                      'Changes to organized ideas never alter your original recording or transcript.',
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
                          onPressed: () => setState(() => _isEditing = true),
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
                            icon: const Icon(Icons.auto_awesome, size: 18),
                            label: const Text(
                              'Process with AI',
                              style: TextStyle(fontWeight: FontWeight.w600),
                            ),
                            onPressed: () =>
                                widget.noteProvider.processNoteAI(note.id),
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
