"""
=============================================================================
 TEST BOOTSTRAP — provide a SECRET_KEY for the test session
=============================================================================
 config.Config deliberately has NO hardcoded SECRET_KEY fallback (deploy
 safety: the production entrypoint serve.py refuses to start without one).

 Tests exercise real signed sessions (login / logout / flash), so they must
 supply a key of their own. pytest imports this conftest.py BEFORE any test
 module, so setting the environment variable here guarantees Config reads a
 stable test-only key before `main` is imported.

 IB HL CS: test isolation - tests never depend on (or leak) a production
 secret; a fixed test key is scoped to the test run only.
"""
import os

os.environ.setdefault('SECRET_KEY', 'fairshare-test-secret-key')
