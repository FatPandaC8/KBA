import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';

enum _AuthMode { welcome, signIn, signUp, verify }

class WelcomeScreen extends StatefulWidget {
  final SettingsService settingsService;
  final BackendService backendService;

  const WelcomeScreen({
    super.key,
    required this.settingsService,
    required this.backendService,
  });

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen> {
  _AuthMode _mode = _AuthMode.welcome;
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _token = TextEditingController();
  bool _busy = false;
  String? _message;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _token.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      if (_mode == _AuthMode.signIn) {
        final body = await widget.backendService.login(
          _email.text.trim(),
          _password.text,
        );
        final token = body['token'] as String?;
        if (token == null || token.isEmpty) {
          throw Exception('No session returned.');
        }
        await widget.settingsService.setSessionToken(token);
      } else {
        final body = await widget.backendService.signup(
          _email.text.trim(),
          _password.text,
        );
        final devToken = body['dev_verification_token'] as String?;
        if (devToken != null && devToken.isNotEmpty) {
          _token.text = devToken;
        }
        setState(() => _mode = _AuthMode.verify);
      }
    } on BackendException catch (e) {
      setState(() => _message = e.message);
    } catch (e) {
      setState(() => _message = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verify() async {
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      await widget.backendService.verifyEmail(_token.text.trim());
      await widget.settingsService.setSessionToken(
        widget.settingsService.sessionToken,
      );
      if (mounted) setState(() => _mode = _AuthMode.welcome);
    } on BackendException catch (e) {
      setState(() => _message = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  InputDecoration _input(String label) => InputDecoration(
    labelText: label,
    filled: true,
    fillColor: Colors.white,
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: EchoColors.border),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: EchoColors.border),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final form = _mode != _AuthMode.welcome;
    return Scaffold(
      backgroundColor: EchoColors.surface,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(28, 32, 28, 24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 660),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Container(
                      width: 42,
                      height: 42,
                      decoration: const BoxDecoration(
                        color: EchoColors.forest,
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(
                        Icons.hub_outlined,
                        color: Colors.white,
                      ),
                    ),
                    const SizedBox(width: 12),
                    const Text(
                      'echo',
                      style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w700,
                        letterSpacing: -1,
                        color: EchoColors.ink,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 72),
                if (!form) ...[
                  Container(
                    height: 190,
                    decoration: BoxDecoration(
                      color: EchoColors.sageSoft,
                      borderRadius: BorderRadius.circular(28),
                    ),
                    child: const Center(
                      child: Icon(
                        Icons.hub_outlined,
                        size: 86,
                        color: EchoColors.forest,
                      ),
                    ),
                  ),
                  const SizedBox(height: 34),
                  const Text(
                    'Remember what matters.',
                    style: TextStyle(
                      fontSize: 34,
                      height: 1.05,
                      fontWeight: FontWeight.w700,
                      letterSpacing: -1.2,
                      color: EchoColors.ink,
                    ),
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Speak naturally. Echo connects the people, ideas, and moments you want to find again.',
                    style: TextStyle(
                      fontSize: 15,
                      height: 1.5,
                      color: EchoColors.muted,
                    ),
                  ),
                  const SizedBox(height: 36),
                  FilledButton(
                    onPressed: () => setState(() => _mode = _AuthMode.signIn),
                    child: const Text('Sign in'),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton(
                    onPressed: () => setState(() => _mode = _AuthMode.signUp),
                    child: const Text('Create an account'),
                  ),
                ] else ...[
                  IconButton(
                    alignment: Alignment.centerLeft,
                    padding: EdgeInsets.zero,
                    onPressed: () => setState(() => _mode = _AuthMode.welcome),
                    icon: const Icon(Icons.arrow_back),
                  ),
                  const SizedBox(height: 22),
                  Text(
                    _mode == _AuthMode.verify
                        ? 'Check your email.'
                        : (_mode == _AuthMode.signUp
                              ? 'Create your Echo.'
                              : 'Welcome back.'),
                    style: const TextStyle(
                      fontSize: 32,
                      fontWeight: FontWeight.w700,
                      letterSpacing: -1,
                      color: EchoColors.ink,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    _mode == _AuthMode.verify
                        ? 'Enter the verification code to continue.'
                        : 'Your private knowledge graph starts with a single thought.',
                    style: const TextStyle(
                      fontSize: 14,
                      color: EchoColors.muted,
                    ),
                  ),
                  const SizedBox(height: 32),
                  if (_mode != _AuthMode.verify) ...[
                    TextField(
                      controller: _email,
                      keyboardType: TextInputType.emailAddress,
                      decoration: _input('Email'),
                    ),
                    const SizedBox(height: 14),
                    TextField(
                      controller: _password,
                      obscureText: true,
                      decoration: _input('Password'),
                    ),
                    const SizedBox(height: 22),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: Text(
                        _mode == _AuthMode.signUp
                            ? 'Create account'
                            : 'Sign in',
                      ),
                    ),
                  ] else ...[
                    TextField(
                      controller: _token,
                      decoration: _input('Verification code'),
                    ),
                    const SizedBox(height: 22),
                    FilledButton(
                      onPressed: _busy ? null : _verify,
                      child: const Text('Verify email'),
                    ),
                  ],
                  if (_message != null) ...[
                    const SizedBox(height: 16),
                    Text(
                      _message!,
                      style: const TextStyle(color: EchoColors.danger),
                    ),
                  ],
                ],
                const SizedBox(height: 48),
                if (!form)
                  const Text(
                    'Your voice, connected.',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 12, color: EchoColors.muted),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
