import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'echo_colors.dart';

class EchoTheme {
  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      scaffoldBackgroundColor: EchoColors.surface,
      colorScheme: const ColorScheme.light(
        surface: EchoColors.surface,
        primary: EchoColors.forest,
        secondary: EchoColors.sage,
        error: EchoColors.danger,
        onSurface: EchoColors.ink,
        onPrimary: Colors.white,
      ),
      textTheme: TextTheme(
        headlineLarge: GoogleFonts.dmSans(
          fontSize: 30,
          fontWeight: FontWeight.w600,
          color: EchoColors.ink,
          letterSpacing: -0.8,
        ),
        headlineMedium: GoogleFonts.dmSans(
          fontSize: 20,
          fontWeight: FontWeight.w600,
          color: EchoColors.ink,
          letterSpacing: -0.4,
        ),
        titleMedium: GoogleFonts.dmSans(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: EchoColors.ink,
        ),
        bodyLarge: GoogleFonts.dmSans(
          fontSize: 14,
          color: EchoColors.ink,
          height: 1.5,
        ),
        bodyMedium: GoogleFonts.dmSans(
          fontSize: 13,
          color: EchoColors.ink,
          height: 1.45,
        ),
        bodySmall: GoogleFonts.dmSans(fontSize: 11, color: EchoColors.muted),
      ),
      dividerTheme: const DividerThemeData(
        color: EchoColors.border,
        thickness: 1,
      ),
      cardTheme: CardThemeData(
        color: EchoColors.card,
        elevation: 0,
        shape: RoundedRectangleBorder(
          side: const BorderSide(color: EchoColors.border),
          borderRadius: BorderRadius.circular(16),
        ),
      ),
    );
  }

  static TextStyle eyebrow = GoogleFonts.dmSans(
    fontSize: 10,
    fontWeight: FontWeight.w700,
    letterSpacing: 1.4,
    color: EchoColors.forest2,
  );
}
