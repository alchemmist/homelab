import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ExistingHumanBrowserAuthPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / 'deploy/identity/browser-auth-policy.json').read_text())
        self.people = json.loads((ROOT / 'deploy/identity/account-mappings.json').read_text())

    def test_only_reviewed_nonowner_is_targeted(self):
        self.assertTrue(self.policy['preserveOwnerRecoveryAndMachineIdentities'])
        self.assertNotIn(self.policy['protectedOwner'], self.policy['humans'])
        self.assertTrue(set(self.policy['humans']).issubset(self.people))
        self.assertEqual(self.policy['humans']['tim']['desiredBrowserAuthentication'], 'authentik-only')

    def test_disable_legacy_rancher_not_the_oidc_account(self):
        target = self.policy['humans']['tim']
        self.assertFalse(target['rancher']['legacyLocalUserEnabled'])
        self.assertTrue(target['rancher']['existingExternalUserEnabled'])
        self.assertTrue(target['preserveExistingDataAndRoles'])
        self.assertFalse(target['grafana']['emailAccountMerging'])
        self.assertFalse(target['grafana']['localPasswordPresent'])

    def test_webui_active_row_is_required_for_oauth(self):
        target = self.policy['humans']['tim']['openWebui']
        self.assertTrue(target['authRowActiveForOAuth'])
        self.assertTrue(target['legacyPasswordReplacedWithDiscardedRandomCredential'])
        self.assertTrue(target['legacySessionStampRevoked'])

    def test_existing_identity_uses_self_setup_not_a_new_operator_password(self):
        enrollment = self.policy['humans']['tim']['idpEnrollment']
        self.assertTrue(enrollment['existingUuidPreserved'])
        self.assertFalse(enrollment['oldPasswordUsable'])
        self.assertFalse(enrollment['operatorSetsHumanPassword'])
        self.assertFalse(enrollment['credentialValuesInGit'])
        self.assertEqual(enrollment['tokenIntent'], 'verification')
        self.assertTrue(enrollment['passwordThenMandatoryMfa'])

    def test_activation_is_token_only_never_create_and_not_emergency_recovery(self):
        flow = json.loads((ROOT / 'deploy/identity/existing-user-activation.json').read_text())
        self.assertEqual(flow['authentication'], 'require_token')
        self.assertEqual(flow['token']['intent'], 'verification')
        self.assertFalse(flow['token']['emergencyRecoveryKey'])
        self.assertTrue(flow['token']['revokeOnExecution'])
        self.assertEqual(flow['token']['lifetimeHours'], 24)
        self.assertEqual(flow['stages'][1]['userCreationMode'], 'never_create')
        self.assertEqual(flow['stages'][2]['notConfiguredAction'], 'configure')
        self.assertIn('homelab-owner', flow['guardExpression'])
        self.assertIn('token, "user_id", None) == user.pk', flow['guardExpression'])
        self.assertFalse(flow['globalBrandRecoveryFlowChanged'])
        self.assertFalse(flow['ownerAuthenticationFlowChanged'])

    def test_umami_is_explicitly_suspended_not_false_oidc_success(self):
        target = self.policy['humans']['tim']['umami']
        self.assertEqual(target['state'], 'suspended-pending-native-oidc')
        self.assertTrue(target['softDisabledWithoutDeletingData'])
        self.assertTrue(target['gatePlusNativePasswordIsNotOidc'])
        self.assertEqual(target['followUpIssue'], 85)


if __name__ == '__main__':
    unittest.main()
