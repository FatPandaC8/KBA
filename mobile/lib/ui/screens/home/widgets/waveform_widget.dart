import 'dart:math';

import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';

class WaveformWidget extends StatelessWidget {
  final bool isRecording;

  const WaveformWidget({super.key, this.isRecording = false});

  @override
  Widget build(BuildContext context) {
    // Generate heights identical to Figma waveform
    final heights = [
      12.0,
      24.0,
      34.0,
      18.0,
      42.0,
      28.0,
      48.0,
      20.0,
      38.0,
      30.0,
      45.0,
      18.0,
      35.0,
      25.0,
      14.0,
    ];

    return SizedBox(
      height: 70,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: heights.map((h) {
          return Container(
            width: 3.5,
            height: isRecording ? max(8.0, h * 0.8) : 10.0,
            margin: const EdgeInsets.symmetric(horizontal: 2.5),
            decoration: BoxDecoration(
              color: isRecording ? EchoColors.forest : EchoColors.sage,
              borderRadius: BorderRadius.circular(4),
            ),
          );
        }).toList(),
      ),
    );
  }
}
