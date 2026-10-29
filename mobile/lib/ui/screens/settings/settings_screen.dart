import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';

import 'package:mobile/ui/widgets/echo_app_bar.dart';

enum _SettingsMode { signIn, signUp, verifyEmail, settings }

class SettingsScreen extends StatefulWidget {
  final SettingsService settingsService;
  final BackendService backendService;
  final VoidCallback onBack;

  const SettingsScreen({
    super.key,
    required this.settingsService,
    required this.backendService,
    required this.onBack,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  _SettingsMode _mode = _SettingsMode.signIn;

  late final TextEditingController _emailController;
  late final TextEditingController _passwordController;
  late final TextEditingController _serverController;
  late final TextEditingController _tokenController;

  bool _obscurePassword = true;
  bool _saving = false;
  String? _statusMessage;
  bool _statusOk = false;
  bool _consentGranted = false;

  @override
  void initState() {
    super.initState();
    _emailController = TextEditingController();
    _passwordController = TextEditingController();
    _serverController = TextEditingController(
      text: widget.settingsService.serverUrl,
    );
    _tokenController = TextEditingController();
    _mode = widget.settingsService.isAuthenticated
        ? _SettingsMode.settings
        : _SettingsMode.signIn;
    _loadConsent();
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _serverController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  Future<void> _loadConsent() async {
    if (!widget.settingsService.isAuthenticated) return;
    try {
      final consent = await widget.backendService.getConsent();
      if (!mounted) return;
      setState(() {
        _consentGranted = (consent['granted'] as bool? ?? false);
      });
    } catch (_) {
      // Consent endpoint may 403 before consent; treat as not granted.
      if (!mounted) return;
      setState(() => _consentGranted = false);
    }
  }

  void _setStatus(String message, bool ok) {
    if (!mounted) return;
    setState(() {
      _statusMessage = message;
      _statusOk = ok;
    });
  }

  Future<void> _signIn() async {
    _setStatus('', false);
    setState(() => _saving = true);
    try {
      final body = await widget.backendService.login(
        _emailController.text.trim(),
        _passwordController.text,
      );
      final token = body['token'] as String?;
      if (token == null || token.isEmpty) {
        _setStatus('Log-in failed: no session returned.', false);
        return;
      }
      await widget.settingsService.setSessionToken(token);
      await _loadConsent();
      if (!mounted) return;
      setState(() {
        _mode = _SettingsMode.settings;
        _saving = false;
        _statusMessage = 'Signed in.';
        _statusOk = true;
      });
    } on BackendException catch (e) {
      _setStatus('Log-in failed: ${e.message}', false);
    } catch (e) {
      _setStatus('Log-in failed: $e', false);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _signUp() async {
    _setStatus('', false);
    setState(() => _saving = true);
    try {
      final body = await widget.backendService.signup(
        _emailController.text.trim(),
        _passwordController.text,
      );
      final devToken = body['dev_verification_token'] as String?;
      if (!mounted) return;
      if (devToken != null && devToken.isNotEmpty) {
        // Development: show the verification token so the flow can be tested
        // without a real mailbox.
        _tokenController.text = devToken;
        setState(() {
          _mode = _SettingsMode.verifyEmail;
          _saving = false;
          _statusMessage =
              'Account created. Enter the verification token shown below.';
          _statusOk = true;
        });
      } else {
        setState(() {
          _mode = _SettingsMode.verifyEmail;
          _saving = false;
          _statusMessage =
              'Account created. A verification token was sent to your email.';
          _statusOk = true;
        });
      }
    } on BackendException catch (e) {
      _setStatus('Sign-up failed: ${e.message}', false);
    } catch (e) {
      _setStatus('Sign-up failed: $e', false);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _verifyEmail() async {
    _setStatus('', false);
    setState(() => _saving = true);
    try {
      await widget.backendService.verifyEmail(_tokenController.text.trim());
      await widget.settingsService.setSessionToken(
        // Re-login is not needed; verification marks the existing session.
        // Fetch a fresh session by logging in again with stored credentials is
        // not possible without storing the password. Instead, the verification
        // endpoint confirms the token; the session remains valid.
        widget.settingsService.sessionToken,
      );
      await _loadConsent();
      if (!mounted) return;
      setState(() {
        _mode = _SettingsMode.settings;
        _saving = false;
        _statusMessage = 'Email verified.';
        _statusOk = true;
      });
    } on BackendException catch (e) {
      _setStatus('Verification failed: ${e.message}', false);
    } catch (e) {
      _setStatus('Verification failed: $e', false);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _setConsent(bool value) async {
    final previous = _consentGranted;
    setState(() => _consentGranted = value);
    try {
      await widget.backendService.updateConsent(value);
      if (!mounted) return;
      setState(() {
        _statusOk = true;
        _statusMessage = value
            ? 'AI-provider consent granted.'
            : 'Consent withdrawn. Recording is blocked until consent is re-granted.';
      });
    } catch (e) {
      setState(() => _consentGranted = previous);
      if (!mounted) return;
      _setStatus(
          'Consent update failed. The change was not applied: $e', false);
    }
  }

  Future<void> _saveServer() async {
    final rawUrl = _serverController.text.trim();
    final uri = Uri.tryParse(rawUrl);
    if (uri == null ||
        !uri.hasScheme ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty) {
      _setStatus(
          'Enter a valid URL starting with http:// or https://.', false);
      return;
    }
    setState(() => _saving = true);
    try {
      widget.settingsService.serverUrl = rawUrl.replaceAll(RegExp(r'/+$'), '');
      if (!mounted) return;
      setState(() {
        _saving = false;
        _statusMessage = 'Server URL saved.';
        _statusOk = true;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _statusMessage = 'Could not save server URL: $e';
        _statusOk = false;
      });
    }
  }

  Future<void> _testConnection() async {
    await _saveServer();
    if (!mounted || _statusMessage == null) return;
    setState(() {
      _saving = true;
      _statusMessage = 'Testing connection…';
    });
    try {
      final result = await widget.backendService.testConnection();
      if (!mounted) return;
      setState(() {
        _saving = false;
        _statusOk = result.ok;
        _statusMessage = result.message;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _statusOk = false;
        _statusMessage = 'Could not reach server: $e';
      });
    }
  }

  Future<void> _logout() async {
    setState(() => _saving = true);
    try {
      await widget.backendService.logout();
    } catch (_) {
      // Ignore logout errors: local session is cleared regardless.
    }
    await widget.settingsService.clearSession();
    if (!mounted) return;
    setState(() {
      _mode = _SettingsMode.signIn;
      _saving = false;
      _statusMessage = 'Signed out.';
      _statusOk = true;
      _emailController.clear();
      _passwordController.clear();
      _tokenController.clear();
    });
  }

  Future<void> _deleteAccount() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Delete your account?'),
        content: const Text(
          'This permanently deletes all your data (audio, knowledge graph, '
          'sessions) and cannot be undone. Backups and third-party copies '
          'already made may persist for the documented retention period.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: TextButton.styleFrom(foregroundColor: EchoColors.danger),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _saving = true);
    try {
      await widget.backendService.deleteAccount();
    } on BackendException catch (e) {
      _setStatus('Account deletion failed: ${e.message}', false);
      return;
    } catch (e) {
      _setStatus('Account deletion failed: $e', false);
      return;
    }
    await widget.settingsService.clearSession();
    if (!mounted) return;
    setState(() {
      _mode = _SettingsMode.signIn;
      _saving = false;
      _statusMessage = 'Account deleted.';
      _statusOk = true;
      _emailController.clear();
      _passwordController.clear();
      _tokenController.clear();
    });
    // Notify the shell that the session ended so the app re-gates.
    widget.onBack();
  }

  Widget _buildAuthForm() {
    final isSignUp = _mode == _SettingsMode.signUp;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          isSignUp ? 'Create account' : 'Sign in',
          style: const TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w700,
            color: EchoColors.ink,
          ),
        ),
        const SizedBox(height: 20),
        TextField(
          controller: _emailController,
          keyboardType: TextInputType.emailAddress,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(
            labelText: 'Email address',
            hintText: 'you@example.com',
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          controller: _passwordController,
          obscureText: _obscurePassword,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(
            labelText: 'Password',
            helperText: 'At least 10 characters, mixed case and a digit.',
            suffixIcon: IconButton(
              tooltip: _obscurePassword ? 'Show password' : 'Hide password',
              icon: Icon(
                _obscurePassword
                    ? Icons.visibility_outlined
                    : Icons.visibility_off_outlined,
              ),
              onPressed: () =>
                  setState(() => _obscurePassword = !_obscurePassword),
            ),
          ),
        ),
        const SizedBox(height: 18),
        if (_statusMessage != null) ...[
          Text(
            _statusMessage!,
            style: TextStyle(
              fontSize: 12,
              height: 1.4,
              color: _statusOk ? EchoColors.forest : EchoColors.danger,
            ),
          ),
          const SizedBox(height: 10),
        ],
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: _saving ? null : _signIn,
                child: const Text('Sign in'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: ElevatedButton(
                onPressed: _saving ? null : _signUp,
                style: ElevatedButton.styleFrom(
                  backgroundColor: EchoColors.forest,
                  foregroundColor: Colors.white,
                ),
                child: Text(isSignUp ? 'Create account' : 'Sign up'),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildVerifyForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Verify email',
          style: TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w700,
            color: EchoColors.ink,
          ),
        ),
        const SizedBox(height: 20),
        const Text(
          'Enter the verification token sent to your email. In development '
          'the token is shown on this screen so the flow can be tested '
          'without a real mailbox.',
          style: TextStyle(fontSize: 12, color: EchoColors.muted),
        ),
        const SizedBox(height: 20),
        TextField(
          controller: _tokenController,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(
            labelText: 'Verification token',
          ),
        ),
        const SizedBox(height: 18),
        if (_statusMessage != null) ...[
          Text(
            _statusMessage!,
            style: TextStyle(
              fontSize: 12,
              height: 1.4,
              color: _statusOk ? EchoColors.forest : EchoColors.danger,
            ),
          ),
          const SizedBox(height: 10),
        ],
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: _saving ? null : () {
                  setState(() => _mode = _SettingsMode.signIn);
                },
                child: const Text('Back to sign in'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: ElevatedButton(
                onPressed: _saving ? null : _verifyEmail,
                style: ElevatedButton.styleFrom(
                  backgroundColor: EchoColors.forest,
                  foregroundColor: Colors.white,
                ),
                child: const Text('Verify'),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildSettingsForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Settings',
          style: TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w700,
            color: EchoColors.ink,
          ),
        ),
        const SizedBox(height: 20),

        const Text(
          'SERVER CONNECTION',
          style: TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.2,
            color: EchoColors.muted,
          ),
        ),
        const SizedBox(height: 10),
        Container(
          width: double.infinity,
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: EchoColors.border),
          ),
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                controller: _serverController,
                keyboardType: TextInputType.url,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: 'Backend URL',
                  hintText: 'http://192.168.1.20:8000',
                  helperText:
                      'USB development: adb reverse tcp:8000 tcp:8000',
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _saving ? null : _saveServer,
                      child: const Text('Save'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: ElevatedButton(
                      onPressed: _saving ? null : _testConnection,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: EchoColors.forest,
                        foregroundColor: Colors.white,
                      ),
                      child: const Text('Test connection'),
                    ),
                  ),
                ],
              ),
              if (_statusMessage != null) ...[
                const SizedBox(height: 10),
                Text(
                  _statusMessage!,
                  style: TextStyle(
                    fontSize: 12,
                    height: 1.4,
                    color: _statusOk
                        ? EchoColors.forest
                        : EchoColors.danger,
                  ),
                ),
              ],
            ],
          ),
        ),

        const SizedBox(height: 24),

        const Text(
          'AI-PROVIDER CONSENT',
          style: TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.2,
            color: EchoColors.muted,
          ),
        ),
        const SizedBox(height: 10),
        Material(
          color: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: const BorderSide(color: EchoColors.border),
          ),
          clipBehavior: Clip.antiAlias,
          child: SwitchListTile(
            activeThumbColor: EchoColors.forest,
            title: const Text(
              'Allow AI processing of recordings',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
            ),
            subtitle: const Text(
              'Recordings are sent to your configured server for transcription '
              'and knowledge extraction. Declining or withdrawing blocks '
              'recording until consent is re-granted.',
              style: TextStyle(fontSize: 11, color: EchoColors.muted),
            ),
            value: _consentGranted,
            onChanged: widget.settingsService.isAuthenticated
                ? _setConsent
                : null,
          ),
        ),

        const SizedBox(height: 24),

        Container(
          width: double.infinity,
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: EchoColors.border),
          ),
          padding: const EdgeInsets.all(16),
          child: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Transparent Processing',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
              SizedBox(height: 6),
              Text(
                'Echo stores your source notes on-device and sends audio '
                'to your configured server for transcription, structured '
                'extraction, and semantic recall. Transcripts are never shown '
                'to you; you may play back your own recordings.',
                style: TextStyle(
                  fontSize: 11,
                  color: EchoColors.muted,
                  height: 1.5,
                ),
              ),
            ],
          ),
        ),

        const SizedBox(height: 32),

        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: _saving ? null : _logout,
                child: const Text('Sign out'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton(
                onPressed: _saving ? null : _deleteAccount,
                style: OutlinedButton.styleFrom(
                  foregroundColor: EchoColors.danger,
                  side: const BorderSide(color: EchoColors.danger),
                ),
                child: const Text('Delete account'),
              ),
            ),
          ],
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: EchoAppBar(
        title: _mode == _SettingsMode.settings ? 'Settings' : 'Account',
        onBack: widget.onBack,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_mode == _SettingsMode.signIn ||
                  _mode == _SettingsMode.signUp) ...[
                _buildAuthForm(),
              ] else if (_mode == _SettingsMode.verifyEmail) ...[
                _buildVerifyForm(),
              ] else ...[
                _buildSettingsForm(),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
