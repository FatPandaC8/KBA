import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/widgets/echo_app_bar.dart';

/// Ask AI (QA-01..QA-05): conversation history, chat input at the bottom,
/// display-only source chips, and a distinct state for every failure class.
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
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scroll = ScrollController();
  bool _showHistory = false;

  @override
  void initState() {
    super.initState();
    widget.noteProvider.loadConversations();
  }

  @override
  void dispose() {
    _controller.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    _controller.clear();
    await widget.noteProvider.askQuestion(text);
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  String _errorLabel(AskMessageModel message) {
    switch (message.errorClass) {
      case 'quota_exhausted':
        return 'Free quota exhausted';
      case 'network_error':
        return 'No connection';
      case 'provider_failure':
        return 'Provider failure';
      default:
        return 'Could not answer';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: EchoAppBar(title: 'Ask AI'),
      body: ListenableBuilder(
        listenable: widget.noteProvider,
        builder: (context, _) {
          final provider = widget.noteProvider;
          final messages = provider.messages;
          final busy = provider.isAsking;

          return SafeArea(
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 4),
                  child: Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'Ask about what you captured',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w700,
                            color: EchoColors.ink,
                          ),
                        ),
                      ),
                      IconButton(
                        tooltip: 'Conversation history',
                        icon: const Icon(
                          Icons.history,
                          color: EchoColors.forest,
                        ),
                        onPressed: () {
                          provider.loadConversations();
                          setState(() => _showHistory = !_showHistory);
                        },
                      ),
                      IconButton(
                        tooltip: 'New conversation',
                        icon: const Icon(
                          Icons.add_comment_outlined,
                          color: EchoColors.forest,
                        ),
                        onPressed: () {
                          provider.startNewConversation();
                          setState(() => _showHistory = false);
                        },
                      ),
                    ],
                  ),
                ),
                if (_showHistory)
                  _ConversationHistory(
                    conversations: provider.conversations,
                    activeId: provider.activeConversationId,
                    onOpen: (id) async {
                      await provider.openConversation(id);
                      if (mounted) setState(() => _showHistory = false);
                    },
                    onDelete: (id) => provider.deleteConversation(id),
                  ),
                if (provider.askError != null)
                  Container(
                    width: double.infinity,
                    margin: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 6,
                    ),
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: EchoColors.dangerSoft,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: EchoColors.danger),
                    ),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.error_outline,
                          size: 16,
                          color: EchoColors.danger,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            provider.askError!,
                            style: const TextStyle(
                              fontSize: 11,
                              color: EchoColors.ink,
                            ),
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.close, size: 16),
                          onPressed: provider.clearAskError,
                        ),
                      ],
                    ),
                  ),
                Expanded(
                  child: messages.isEmpty
                      ? const _AskEmptyState()
                      : ListView.builder(
                          controller: _scroll,
                          padding: const EdgeInsets.fromLTRB(20, 8, 20, 12),
                          itemCount: messages.length,
                          itemBuilder: (context, index) {
                            final message = messages[index];
                            if (message.isUser) {
                              return _UserBubble(content: message.content);
                            }
                            return _AssistantBubble(
                              message: message,
                              errorLabel: _errorLabel(message),
                            );
                          },
                        ),
                ),
                if (busy)
                  const Padding(
                    padding: EdgeInsets.only(bottom: 6),
                    child: Text(
                      'Searching your knowledge…',
                      style: TextStyle(fontSize: 11, color: EchoColors.muted),
                    ),
                  ),
                _AskInput(
                  controller: _controller,
                  busy: busy,
                  onSend: _send,
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _AskEmptyState extends StatelessWidget {
  const _AskEmptyState();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 28),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 62,
              height: 62,
              decoration: const BoxDecoration(
                color: EchoColors.sageSoft,
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.chat_bubble_outline,
                color: EchoColors.forest,
                size: 28,
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              'Ask your own knowledge',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: EchoColors.ink,
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              'Answers come only from the entities and relationships you captured. If the evidence is missing, the assistant says so.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 13,
                height: 1.45,
                color: EchoColors.muted,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _UserBubble extends StatelessWidget {
  final String content;

  const _UserBubble({required this.content});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10, left: 40),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: EchoColors.forest,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Text(
          content,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 13,
            height: 1.4,
          ),
        ),
      ),
    );
  }
}

class _AssistantBubble extends StatelessWidget {
  final AskMessageModel message;
  final String errorLabel;

  const _AssistantBubble({required this.message, required this.errorLabel});

  @override
  Widget build(BuildContext context) {
    final failed = message.isFailed;
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10, right: 30),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: failed ? EchoColors.dangerSoft : Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: failed ? EchoColors.danger : EchoColors.border,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (failed) ...[
              Row(
                children: [
                  const Icon(
                    Icons.error_outline,
                    size: 14,
                    color: EchoColors.danger,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    errorLabel,
                    style: const TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: EchoColors.danger,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
            ],
            Text(
              message.content,
              style: const TextStyle(
                fontSize: 13,
                height: 1.5,
                color: EchoColors.ink,
              ),
            ),
            if (message.citations.isNotEmpty) ...[
              const SizedBox(height: 10),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: message.citations
                    .map((citation) => _CitationChip(citation: citation))
                    .toList(),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Display-only source chip (D13 / QA-04): deliberately not tappable.
class _CitationChip extends StatelessWidget {
  final CitationModel citation;

  const _CitationChip({required this.citation});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: citation.deleted
            ? const Color(0xFFF1F1F1)
            : EchoColors.sageSoft,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: EchoColors.border),
      ),
      child: Text(
        citation.deleted ? '${citation.name} (deleted)' : citation.name,
        style: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w600,
          color: citation.deleted ? EchoColors.muted : EchoColors.forest,
        ),
      ),
    );
  }
}

class _AskInput extends StatelessWidget {
  final TextEditingController controller;
  final bool busy;
  final VoidCallback onSend;

  const _AskInput({
    required this.controller,
    required this.busy,
    required this.onSend,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.fromLTRB(
        20,
        8,
        20,
        8 + MediaQuery.of(context).padding.bottom,
      ),
      decoration: const BoxDecoration(
        color: EchoColors.surface,
        border: Border(top: BorderSide(color: EchoColors.border)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: const Color(0xFFCFD2CC)),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 14),
              child: TextField(
                controller: controller,
                enabled: !busy,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => busy ? null : onSend(),
                style: const TextStyle(fontSize: 13, color: EchoColors.ink),
                decoration: const InputDecoration(
                  hintText: 'Ask about what you’ve captured',
                  hintStyle: TextStyle(
                    color: Color(0xFF9A9D97),
                    fontSize: 13,
                  ),
                  border: InputBorder.none,
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: busy ? EchoColors.muted : EchoColors.forest,
              borderRadius: BorderRadius.circular(13),
            ),
            child: IconButton(
              tooltip: 'Send question',
              icon: const Icon(
                Icons.arrow_upward,
                color: Colors.white,
                size: 18,
              ),
              padding: EdgeInsets.zero,
              onPressed: busy ? null : onSend,
            ),
          ),
        ],
      ),
    );
  }
}

class _ConversationHistory extends StatelessWidget {
  final List<ConversationSummaryModel> conversations;
  final String? activeId;
  final ValueChanged<String> onOpen;
  final ValueChanged<String> onDelete;

  const _ConversationHistory({
    required this.conversations,
    required this.activeId,
    required this.onOpen,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(20, 4, 20, 8),
      padding: const EdgeInsets.symmetric(vertical: 6),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: EchoColors.border),
      ),
      constraints: const BoxConstraints(maxHeight: 240),
      child: conversations.isEmpty
          ? const Padding(
              padding: EdgeInsets.all(14),
              child: Text(
                'No past conversations yet.',
                style: TextStyle(fontSize: 12, color: EchoColors.muted),
              ),
            )
          : ListView.builder(
              shrinkWrap: true,
              itemCount: conversations.length,
              itemBuilder: (context, index) {
                final conversation = conversations[index];
                final active = conversation.id == activeId;
                return ListTile(
                  dense: true,
                  selected: active,
                  title: Text(
                    conversation.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                    ),
                  ),
                  subtitle: Text(
                    _formatDate(conversation.updatedAt),
                    style: const TextStyle(fontSize: 10),
                  ),
                  onTap: () => onOpen(conversation.id),
                  trailing: IconButton(
                    tooltip: 'Delete conversation',
                    icon: const Icon(
                      Icons.delete_outline,
                      size: 18,
                      color: EchoColors.danger,
                    ),
                    onPressed: () => onDelete(conversation.id),
                  ),
                );
              },
            ),
    );
  }

  String _formatDate(String raw) {
    final parsed = DateTime.tryParse(raw);
    if (parsed == null) return '';
    return DateFormat('MMM d, h:mm a').format(parsed.toLocal());
  }
}
