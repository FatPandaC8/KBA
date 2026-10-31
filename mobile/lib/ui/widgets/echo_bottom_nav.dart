import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';

class EchoBottomNav extends StatelessWidget {
  final int currentIndex;
  final ValueChanged<int> onTap;
  final VoidCallback onCenterCapture;

  const EchoBottomNav({
    super.key,
    required this.currentIndex,
    required this.onTap,
    required this.onCenterCapture,
  });

  @override
  Widget build(BuildContext context) {
    const double fabDiameter = 58.0;
    // Grow the bar slightly with the system font scale instead of letting
    // labels overflow the fixed template height.
    final textScale = MediaQuery.textScalerOf(context)
        .scale(1.0)
        .clamp(0.8, 1.4);
    final barHeight = 72.0 + (textScale - 1.0) * 26.0;
    final bottomPadding = MediaQuery.of(context).padding.bottom;

    return MediaQuery.withClampedTextScaling(
      maxScaleFactor: 1.3,
      child: SizedBox(
        height: barHeight + bottomPadding,
        child: Stack(
          clipBehavior: Clip.none,
          alignment: Alignment.bottomCenter,
          children: [
            // Background Bar Surface with Top Divider aligned to center of FAB
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              height: barHeight + bottomPadding - 18,
              child: Container(
                decoration: const BoxDecoration(
                  color: EchoColors.surface,
                  border: Border(
                    top: BorderSide(color: EchoColors.border, width: 1.0),
                  ),
                ),
              ),
            ),

            // Main Navigation Row
            Positioned(
              left: 0,
              right: 0,
              bottom: bottomPadding,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 32),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    // Left Action: Graph
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: _buildNavItem(
                        1,
                        'Graph',
                        Icons.hub_outlined,
                        Icons.hub,
                      ),
                    ),

                    // Center Prominent Capture FAB
                    Semantics(
                      button: true,
                      label: 'Start voice capture',
                      excludeSemantics: true,
                      child: GestureDetector(
                        onTap: onCenterCapture,
                        behavior: HitTestBehavior.opaque,
                        child: Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Container(
                                width: fabDiameter,
                                height: fabDiameter,
                                decoration: BoxDecoration(
                                  color: EchoColors.forest,
                                  shape: BoxShape.circle,
                                  boxShadow: [
                                    BoxShadow(
                                      color: EchoColors.forest.withValues(
                                        alpha: 0.35,
                                      ),
                                      blurRadius: 10,
                                      offset: const Offset(0, 4),
                                    ),
                                  ],
                                ),
                                child: const Icon(
                                  Icons.mic,
                                  color: Colors.white,
                                  size: 30,
                                ),
                              ),
                              const SizedBox(height: 2),
                              const Text(
                                'Record',
                                style: TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.w700,
                                  color: EchoColors.forest,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),

                    // Right Action: none — Ask AI was removed from Echo
                    // (U2). A clear placeholder keeps the capture FAB
                    // optically centered in the two-tab layout.
                    const SizedBox(width: 60),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNavItem(
    int index,
    String label,
    IconData icon,
    IconData activeIcon,
  ) {
    final active = currentIndex == index;
    return Semantics(
      button: true,
      selected: active,
      label: label,
      excludeSemantics: true,
      child: GestureDetector(
        onTap: () => onTap(index),
        behavior: HitTestBehavior.opaque,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              height: 36,
              width: 60,
              decoration: BoxDecoration(
                color: active ? EchoColors.sageSoft : Colors.transparent,
                borderRadius: BorderRadius.circular(20),
              ),
              child: Icon(
                active ? activeIcon : icon,
                color: active ? EchoColors.forest : EchoColors.muted,
                size: 22,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              label,
              style: TextStyle(
                fontSize: 11,
                fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                color: active ? EchoColors.forest : EchoColors.muted,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
