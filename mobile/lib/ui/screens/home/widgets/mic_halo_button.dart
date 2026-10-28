import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';

class MicHaloButton extends StatelessWidget {
  final VoidCallback onStartRecord;
  final VoidCallback onStopRecord;
  final VoidCallback onCancelRecord;
  final bool isRecording;
  final bool isProcessing;

  const MicHaloButton({
    super.key,
    required this.onStartRecord,
    required this.onStopRecord,
    required this.onCancelRecord,
    this.isRecording = false,
    this.isProcessing = false,
  });

  @override
  Widget build(BuildContext context) {
    final label = isProcessing
        ? 'Processing recording'
        : (isRecording ? 'Stop voice recording' : 'Start voice recording');
    return Semantics(
      button: !isProcessing,
      enabled: !isProcessing,
      label: label,
      hint: isRecording
          ? 'Double tap to stop recording'
          : 'Double tap to start recording, or press and hold',
      onTap: isProcessing
          ? null
          : () {
              if (isRecording) {
                onStopRecord();
              } else {
                onStartRecord();
              }
            },
      child: ExcludeSemantics(
        child: Listener(
          behavior: HitTestBehavior.opaque,
          onPointerDown: (_) {
            if (!isProcessing) {
              onStartRecord();
            }
          },
          onPointerUp: (_) {
            onStopRecord();
          },
          onPointerCancel: (_) {
            onCancelRecord();
          },
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            width: isRecording ? 220 : 200,
            height: isRecording ? 220 : 200,
            decoration: BoxDecoration(
              color: isRecording
                  ? const Color(0xFFFDE8E6)
                  : const Color(0xFFE9EEE6),
              shape: BoxShape.circle,
            ),
            alignment: Alignment.center,
            child: Container(
              width: isRecording ? 148 : 138,
              height: isRecording ? 148 : 138,
              decoration: BoxDecoration(
                color: isRecording ? EchoColors.danger : EchoColors.forest,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: (isRecording ? EchoColors.danger : EchoColors.forest)
                        .withValues(alpha: 0.28),
                    blurRadius: 28,
                    offset: const Offset(0, 10),
                  ),
                ],
              ),
              child: isProcessing
                  ? const SizedBox(
                      width: 44,
                      height: 44,
                      child: CircularProgressIndicator(
                        color: Colors.white,
                        strokeWidth: 3.5,
                      ),
                    )
                  : Icon(
                      isRecording ? Icons.mic : Icons.mic_none,
                      color: Colors.white,
                      size: 52,
                    ),
            ),
          ),
        ),
      ),
    );
  }
}
