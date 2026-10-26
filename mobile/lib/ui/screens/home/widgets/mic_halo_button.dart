import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';

class MicHaloButton extends StatelessWidget {
  final VoidCallback onTap;
  final bool isRecording;

  const MicHaloButton({
    super.key,
    required this.onTap,
    this.isRecording = false,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        width: isRecording ? 165 : 154,
        height: isRecording ? 165 : 154,
        decoration: BoxDecoration(
          color: isRecording
              ? const Color(0xFFFDE8E6)
              : const Color(0xFFE9EEE6),
          shape: BoxShape.circle,
        ),
        alignment: Alignment.center,
        child: Container(
          width: 102,
          height: 102,
          decoration: BoxDecoration(
            color: isRecording ? EchoColors.danger : EchoColors.forest,
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: (isRecording ? EchoColors.danger : EchoColors.forest)
                    .withValues(alpha: 0.25),
                blurRadius: 24,
                offset: const Offset(0, 9),
              ),
            ],
          ),
          child: Icon(
            isRecording ? Icons.stop : Icons.mic_none,
            color: Colors.white,
            size: 38,
          ),
        ),
      ),
    );
  }
}
