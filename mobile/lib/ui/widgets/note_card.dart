import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/data/models/note.dart';

class NoteCard extends StatelessWidget {
  final Note note;
  final VoidCallback onTap;
  final VoidCallback? onRetry;

  const NoteCard({
    super.key,
    required this.note,
    required this.onTap,
    this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    final dateFormat = DateFormat('MMM d, h:mm a');
    final formattedDate = dateFormat.format(note.createdAt);

    final isFailed = note.status == ProcessingStatus.failed;
    final isProcessing =
        note.status == ProcessingStatus.transcribing ||
        note.status == ProcessingStatus.structuring ||
        note.status == ProcessingStatus.pending;

    String snippet =
        note.summary ??
        (note.transcript?.isNotEmpty == true
            ? note.transcript!
            : note.originalContent);
    if (snippet.isEmpty) snippet = 'No content';

    return Container(
      decoration: BoxDecoration(
        color: EchoColors.card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: EchoColors.border),
        boxShadow: const [
          BoxShadow(
            color: Color.fromRGBO(35, 42, 37, 0.035),
            blurRadius: 10,
            offset: Offset(0, 3),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(16),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      Expanded(
                        child: Text(
                          note.title,
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: EchoColors.ink,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const Icon(
                        Icons.chevron_right,
                        color: Color(0xFF9BA099),
                        size: 20,
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
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
                  const SizedBox(height: 8),
                  Text(
                    formattedDate,
                    style: const TextStyle(
                      fontSize: 10,
                      color: Color(0xFF979B95),
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (note.status != ProcessingStatus.ready &&
              note.status != ProcessingStatus.rawOnly) ...[
            const Divider(height: 1, color: Color(0xFFEFF0EC)),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              decoration: BoxDecoration(
                color: isFailed ? const Color(0xFFFCF6F4) : Colors.transparent,
                borderRadius: const BorderRadius.vertical(
                  bottom: Radius.circular(15),
                ),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        decoration: BoxDecoration(
                          color: isFailed
                              ? EchoColors.danger
                              : (isProcessing
                                    ? EchoColors.forest
                                    : const Color(0xFF6F8F74)),
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        isFailed
                            ? 'Organization failed · Original saved'
                            : (isProcessing ? 'Organizing ideas…' : 'Ready'),
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          color: isFailed
                              ? EchoColors.danger
                              : EchoColors.forest2,
                        ),
                      ),
                    ],
                  ),
                  if (isFailed && onRetry != null)
                    GestureDetector(
                      onTap: onRetry,
                      child: const Row(
                        children: [
                          Icon(
                            Icons.refresh,
                            size: 14,
                            color: EchoColors.danger,
                          ),
                          SizedBox(width: 4),
                          Text(
                            'Retry',
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                              color: EchoColors.danger,
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
