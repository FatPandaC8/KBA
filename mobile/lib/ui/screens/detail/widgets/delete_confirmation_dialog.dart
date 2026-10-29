import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';

class DeleteConfirmationDialog extends StatelessWidget {
  final VoidCallback onConfirmDelete;

  const DeleteConfirmationDialog({super.key, required this.onConfirmDelete});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: EchoColors.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 50,
              height: 50,
              decoration: const BoxDecoration(
                color: EchoColors.dangerSoft,
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.delete_outline,
                color: EchoColors.danger,
                size: 24,
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              'Delete this capture?',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: EchoColors.ink,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'This removes the audio recording and organized ideas. This can’t be undone.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 13,
                color: EchoColors.muted,
                height: 1.45,
              ),
            ),
            const SizedBox(height: 20),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: EchoColors.danger,
                  foregroundColor: Colors.white,
                  elevation: 0,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
                onPressed: () {
                  Navigator.of(context).pop();
                  onConfirmDelete();
                },
                child: const Text(
                  'Delete permanently',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton(
                style: OutlinedButton.styleFrom(
                  foregroundColor: EchoColors.forest,
                  side: const BorderSide(color: Color(0xFFBFC8BD)),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
                onPressed: () => Navigator.of(context).pop(),
                child: const Text(
                  'Keep capture',
                  style: TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
