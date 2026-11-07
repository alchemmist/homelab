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
        self.assertTrue(target['rancher']['currentExternalUserEnabled'])
        self.assertTrue(target['preserveExistingDataAndRoles'])
        self.assertFalse(target['grafana']['emailAccountMerging'])
        self.assertFalse(target['grafana']['localPasswordPresent'])

    def test_webui_active_row_is_required_for_oauth(self):
        target = self.policy['humans']['tim']['openWebui']
        self.assertTrue(target['authRowActiveForOAuth'])
        self.assertTrue(target['legacyPasswordReplacedWithDiscardedRandomCredential'])
        self.assertTrue(target['legacySessionStampRevoked'])

    def test_fresh_native_user_without_custom_activation(self):
        enrollment = self.policy['humans']['tim']['idpEnrollment']
        self.assertTrue(enrollment['nativeCreateUser'])
        self.assertFalse(enrollment['passwordAssigned'])
        self.assertFalse(enrollment['mfaEnrolled'])
        self.assertFalse(enrollment['customActivationFlow'])
        self.assertFalse(enrollment['activationLinkIssued'])
        self.assertFalse((ROOT / 'deploy/identity/existing-user-activation.json').exists())
        self.assertEqual(self.people['tim']['idpUserUuid'], '6015c85b-82e9-49ce-a4e3-0270c676e26d')

    def test_native_rancher_replacement_preserves_retired_identity_and_grants(self):
        rancher = self.policy['humans']['tim']['rancher']
        self.assertTrue(rancher['nativePrincipalIsImmutable'])
        self.assertFalse(rancher['retiredExternalUserEnabled'])
        self.assertEqual(rancher['currentExternalUserId'], self.people['tim']['rancherOidcUserId'])
        self.assertEqual(self.people['tim']['rancherBindingPrefix'], 'identity-tim-v2-')
        self.assertTrue(rancher['retainDisabledLegacyRecordAndInertGrantHistory'])

    def test_umami_is_explicitly_suspended_not_false_oidc_success(self):
        target = self.policy['humans']['tim']['umami']
        self.assertEqual(target['state'], 'suspended-pending-native-oidc')
        self.assertTrue(target['softDisabledWithoutDeletingData'])
        self.assertTrue(target['gatePlusNativePasswordIsNotOidc'])
        self.assertEqual(target['followUpIssue'], 85)


if __name__ == '__main__':
    unittest.main()
