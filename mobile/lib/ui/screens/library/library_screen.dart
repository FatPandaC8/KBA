import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/core/theme/echo_theme.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/widgets/echo_app_bar.dart';
import 'package:mobile/ui/widgets/note_card.dart';
import 'package:mobile/ui/screens/home/widgets/text_capture_dialog.dart';

import 'widgets/knowledge_graph_widget.dart';

class LibraryScreen extends StatefulWidget {
  final NoteProvider noteProvider;
  final Function(String noteId) onOpenDetail;
  final VoidCallback onOpenHome;

  const LibraryScreen({
    super.key,
    required this.noteProvider,
    required this.onOpenDetail,
    required this.onOpenHome,
  });

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  final TextEditingController _searchController = TextEditingController();
  String _filter = '';
  String _activeView = 'list'; // 'list' or 'graph'

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _openTextCapture() {
    showDialog(
      context: context,
      builder: (_) => TextCaptureDialog(
        onSave: (text) async {
          final note = await widget.noteProvider.createTextNote(text);
          if (mounted) {
            widget.onOpenDetail(note.id);
          }
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: const EchoAppBar(title: 'Library'),
      body: ListenableBuilder(
        listenable: widget.noteProvider,
        builder: (context, _) {
          final allNotes = widget.noteProvider.notes;
          final filteredNotes = allNotes.where((note) {
            if (_filter.isEmpty) return true;
            final query = _filter.toLowerCase();
            return note.title.toLowerCase().contains(query) ||
                note.originalContent.toLowerCase().contains(query) ||
                (note.summary?.toLowerCase().contains(query) ?? false) ||
                (note.transcript?.toLowerCase().contains(query) ?? false);
          }).toList();

          return SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('YOUR KNOWLEDGE', style: EchoTheme.eyebrow),
                          const SizedBox(height: 4),
                          Text(
                            _activeView == 'list'
                                ? 'All captures'
                                : 'Connected ideas',
                            style: const TextStyle(
                              fontSize: 26,
                              fontWeight: FontWeight.w700,
                              color: EchoColors.ink,
                              letterSpacing: -0.5,
                            ),
                          ),
                        ],
                      ),

                      // Figma View Toggle (List vs Graph)
                      Container(
                        padding: const EdgeInsets.all(3),
                        decoration: BoxDecoration(
                          color: const Color(0xFFE9EBE6),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Row(
                          children: [
                            GestureDetector(
                              onTap: () => setState(() => _activeView = 'list'),
                              child: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 10,
                                  vertical: 6,
                                ),
                                decoration: BoxDecoration(
                                  color: _activeView == 'list'
                                      ? Colors.white
                                      : Colors.transparent,
                                  borderRadius: BorderRadius.circular(9),
                                  boxShadow: _activeView == 'list'
                                      ? [
                                          const BoxShadow(
                                            color: Color.fromRGBO(
                                              35,
                                              42,
                                              37,
                                              0.09,
                                            ),
                                            blurRadius: 4,
                                            offset: Offset(0, 1),
                                          ),
                                        ]
                                      : null,
                                ),
                                child: Row(
                                  children: [
                                    Icon(
                                      Icons.list,
                                      size: 16,
                                      color: _activeView == 'list'
                                          ? EchoColors.forest
                                          : EchoColors.muted,
                                    ),
                                    const SizedBox(width: 4),
                                    Text(
                                      'List',
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: FontWeight.w600,
                                        color: _activeView == 'list'
                                            ? EchoColors.forest
                                            : EchoColors.muted,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                            GestureDetector(
                              onTap: () {
                                FocusScope.of(context).unfocus();
                                setState(() => _activeView = 'graph');
                              },
                              child: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 10,
                                  vertical: 6,
                                ),
                                decoration: BoxDecoration(
                                  color: _activeView == 'graph'
                                      ? Colors.white
                                      : Colors.transparent,
                                  borderRadius: BorderRadius.circular(9),
                                  boxShadow: _activeView == 'graph'
                                      ? [
                                          const BoxShadow(
                                            color: Color.fromRGBO(
                                              35,
                                              42,
                                              37,
                                              0.09,
                                            ),
                                            blurRadius: 4,
                                            offset: Offset(0, 1),
                                          ),
                                        ]
                                      : null,
                                ),
                                child: Row(
                                  children: [
                                    Icon(
                                      Icons.hub_outlined,
                                      size: 16,
                                      color: _activeView == 'graph'
                                          ? EchoColors.forest
                                          : EchoColors.muted,
                                    ),
                                    const SizedBox(width: 4),
                                    Text(
                                      'Graph',
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: FontWeight.w600,
                                        color: _activeView == 'graph'
                                            ? EchoColors.forest
                                            : EchoColors.muted,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),

                  const SizedBox(height: 14),

                  // Library Search Input
                  Container(
                    height: 48,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: EchoColors.border),
                    ),
                    padding: const EdgeInsets.symmetric(horizontal: 14),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.search,
                          size: 20,
                          color: EchoColors.muted,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: TextField(
                            controller: _searchController,
                            onChanged: (val) => setState(() => _filter = val),
                            style: const TextStyle(
                              fontSize: 13,
                              color: EchoColors.ink,
                            ),
                            decoration: const InputDecoration(
                              hintText: 'Search your library',
                              hintStyle: TextStyle(
                                color: Color(0xFF9A9D97),
                                fontSize: 13,
                              ),
                              border: InputBorder.none,
                            ),
                          ),
                        ),
                        if (_filter.isNotEmpty)
                          GestureDetector(
                            onTap: () {
                              _searchController.clear();
                              setState(() => _filter = '');
                            },
                            child: const Icon(
                              Icons.close,
                              size: 18,
                              color: EchoColors.muted,
                            ),
                          ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 14),

                  // Content Body: List View or Graph View
                  if (_activeView == 'graph') ...[
                    KnowledgeGraphWidget(
                      noteProvider: widget.noteProvider,
                      onOpenDetail: widget.onOpenDetail,
                      searchQuery: _filter,
                    ),
                  ] else ...[
                    Text(
                      '${filteredNotes.length} ITEMS · NEWEST FIRST',
                      style: const TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1.1,
                        color: EchoColors.muted,
                      ),
                    ),
                    const SizedBox(height: 12),
                    filteredNotes.isEmpty
                        ? Padding(
                            padding: const EdgeInsets.symmetric(vertical: 60),
                            child: Center(
                              child: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  Container(
                                    width: 56,
                                    height: 56,
                                    decoration: const BoxDecoration(
                                      color: EchoColors.sageSoft,
                                      shape: BoxShape.circle,
                                    ),
                                    child: const Icon(
                                      Icons.library_books_outlined,
                                      color: EchoColors.forest,
                                      size: 28,
                                    ),
                                  ),
                                  const SizedBox(height: 16),
                                  Text(
                                    _filter.isEmpty
                                        ? 'No captures yet'
                                        : 'No matching captures',
                                    style: const TextStyle(
                                      fontSize: 16,
                                      fontWeight: FontWeight.w600,
                                      color: EchoColors.ink,
                                    ),
                                  ),
                                  const SizedBox(height: 6),
                                  Text(
                                    _filter.isEmpty
                                        ? 'Record audio or type a note to begin.'
                                        : 'Try another search term.',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      color: EchoColors.muted,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          )
                        : ListView.separated(
                            shrinkWrap: true,
                            physics: const NeverScrollableScrollPhysics(),
                            itemCount: filteredNotes.length,
                            separatorBuilder: (_, _) =>
                                const SizedBox(height: 12),
                            itemBuilder: (context, index) {
                              final note = filteredNotes[index];
                              return NoteCard(
                                note: note,
                                onTap: () => widget.onOpenDetail(note.id),
                                onRetry: () => widget.noteProvider
                                    .syncCaptureToBackend(note.id),
                              );
                            },
                          ),
                  ],
                ],
              ),
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: EchoColors.forest,
        foregroundColor: Colors.white,
        elevation: 4,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        icon: const Icon(Icons.add, size: 20),
        label: const Text(
          'Capture',
          style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
        ),
        onPressed: _openTextCapture,
      ),
    );
  }
}
