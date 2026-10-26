import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/core/theme/echo_theme.dart';
import 'package:mobile/state/note_provider.dart';

import 'package:mobile/ui/widgets/echo_app_bar.dart';

class RecallScreen extends StatefulWidget {
  final NoteProvider noteProvider;
  final Function(String noteId) onOpenDetail;

  const RecallScreen({
    super.key,
    required this.noteProvider,
    required this.onOpenDetail,
  });

  @override
  State<RecallScreen> createState() => _RecallScreenState();
}

class _RecallScreenState extends State<RecallScreen> {
  final TextEditingController _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _executeSearch(String query) {
    widget.noteProvider.search(query);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: const EchoAppBar(title: 'Recall'),
      body: ListenableBuilder(
        listenable: widget.noteProvider,
        builder: (context, _) {
          final isSearching = widget.noteProvider.isLoading;
          final query = widget.noteProvider.searchQuery;
          final results = widget.noteProvider.searchResults;

          return SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('SEARCH BY MEANING', style: EchoTheme.eyebrow),
                  const SizedBox(height: 6),
                  const Text(
                    'What do you want to remember?',
                    style: TextStyle(
                      fontSize: 27,
                      fontWeight: FontWeight.w700,
                      color: EchoColors.ink,
                      letterSpacing: -0.6,
                    ),
                  ),
                  const SizedBox(height: 18),

                  // Search Box matching Figma
                  Container(
                    height: 54,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: const Color(0xFFCFD2CC)),
                    ),
                    padding: const EdgeInsets.only(left: 16, right: 8),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.search,
                          size: 20,
                          color: EchoColors.muted,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: TextField(
                            controller: _searchController,
                            style: const TextStyle(
                              fontSize: 13,
                              color: EchoColors.ink,
                            ),
                            decoration: const InputDecoration(
                              hintText: 'Ask about what you’ve captured',
                              hintStyle: TextStyle(
                                color: Color(0xFF9A9D97),
                                fontSize: 13,
                              ),
                              border: InputBorder.none,
                            ),
                            onChanged: _executeSearch,
                            onSubmitted: _executeSearch,
                          ),
                        ),
                        Container(
                          width: 36,
                          height: 36,
                          decoration: BoxDecoration(
                            color: EchoColors.forest,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: IconButton(
                            icon: const Icon(
                              Icons.arrow_upward,
                              color: Colors.white,
                              size: 18,
                            ),
                            padding: EdgeInsets.zero,
                            onPressed: () =>
                                _executeSearch(_searchController.text),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),

                  // States
                  if (query.isEmpty) ...[
                    // Empty Initial State
                    Center(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 40),
                        child: Column(
                          children: [
                            Container(
                              width: 62,
                              height: 62,
                              decoration: const BoxDecoration(
                                color: EchoColors.sageSoft,
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(
                                Icons.search,
                                color: EchoColors.forest,
                                size: 28,
                              ),
                            ),
                            const SizedBox(height: 16),
                            const Text(
                              'Recall from your own thinking',
                              style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w700,
                                color: EchoColors.ink,
                              ),
                            ),
                            const SizedBox(height: 6),
                            const Text(
                              'Search by keywords, ideas, or topics in your saved notes.',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                fontSize: 13,
                                color: EchoColors.muted,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ] else if (isSearching) ...[
                    const Center(
                      child: Padding(
                        padding: EdgeInsets.symmetric(vertical: 60),
                        child: Column(
                          children: [
                            CircularProgressIndicator(color: EchoColors.forest),
                            SizedBox(height: 16),
                            Text(
                              'Searching your knowledge…',
                              style: TextStyle(fontWeight: FontWeight.w600),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ] else if (results.isEmpty) ...[
                    Center(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 40),
                        child: Column(
                          children: [
                            Container(
                              width: 60,
                              height: 60,
                              decoration: const BoxDecoration(
                                color: EchoColors.sageSoft,
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(
                                Icons.search_off,
                                color: EchoColors.forest,
                                size: 28,
                              ),
                            ),
                            const SizedBox(height: 16),
                            const Text(
                              'No matching knowledge yet',
                              style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w700,
                                color: EchoColors.ink,
                              ),
                            ),
                            const SizedBox(height: 6),
                            const Text(
                              'Try different words, or capture a thought on this topic.',
                              style: TextStyle(
                                fontSize: 13,
                                color: EchoColors.muted,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ] else ...[
                    // Search Results
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          'Sources',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: EchoColors.ink,
                          ),
                        ),
                        Text(
                          '${results.length} matches',
                          style: const TextStyle(
                            fontSize: 12,
                            color: EchoColors.muted,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    ListView.separated(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      itemCount: results.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 10),
                      itemBuilder: (context, index) {
                        final item = results[index];
                        final snippet =
                            item.summary ??
                            (item.transcript?.isNotEmpty == true
                                ? item.transcript!
                                : item.originalContent);

                        return InkWell(
                          onTap: () => widget.onOpenDetail(item.id),
                          borderRadius: BorderRadius.circular(16),
                          child: Container(
                            decoration: BoxDecoration(
                              color: Colors.white,
                              borderRadius: BorderRadius.circular(16),
                              border: Border.all(color: EchoColors.border),
                            ),
                            padding: const EdgeInsets.all(14),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Container(
                                  width: 24,
                                  height: 24,
                                  decoration: BoxDecoration(
                                    color: EchoColors.sageSoft,
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  alignment: Alignment.center,
                                  child: Text(
                                    '${index + 1}',
                                    style: const TextStyle(
                                      fontSize: 11,
                                      fontWeight: FontWeight.w700,
                                      color: EchoColors.forest,
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        item.title,
                                        style: const TextStyle(
                                          fontSize: 14,
                                          fontWeight: FontWeight.w700,
                                          color: EchoColors.ink,
                                        ),
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        snippet,
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: EchoColors.muted,
                                          height: 1.45,
                                        ),
                                        maxLines: 2,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 6),
                                const Icon(
                                  Icons.chevron_right,
                                  color: Color(0xFF9BA099),
                                  size: 20,
                                ),
                              ],
                            ),
                          ),
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
    );
  }
}
