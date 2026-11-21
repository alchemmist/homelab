import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ExistingHumanBrowserAuthPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / "deploy/identity/browser-auth-policy.json").read_text())
        self.people = json.loads((ROOT / "deploy/identity/account-mappings.json").read_text())

    def test_only_reviewed_nonowner_is_targeted(self):
        assert self.policy["preserveOwnerRecoveryAndMachineIdentities"]
        assert self.policy["protectedOwner"] not in self.policy["humans"]
        assert set(self.policy["humans"]).issubset(self.people)
        assert (
            self.policy["humans"]["antropophag"]["desiredBrowserAuthentication"] == "authentik-only"
        )

    def test_disable_legacy_rancher_not_the_oidc_account(self):
        target = self.policy["humans"]["antropophag"]
        assert not target["rancher"]["legacyLocalUserEnabled"]
        assert target["rancher"]["currentExternalUserEnabled"]
        assert target["preserveExistingDataAndRoles"]
        assert not target["grafana"]["emailAccountMerging"]
        assert not target["grafana"]["localPasswordPresent"]

    def test_webui_active_row_is_required_for_oauth(self):
        target = self.policy["humans"]["antropophag"]["openWebui"]
        assert target["authRowActiveForOAuth"]
        assert target["legacyPasswordReplacedWithDiscardedRandomCredential"]
        assert target["legacySessionStampRevoked"]

    def test_fresh_native_user_without_custom_activation(self):
        enrollment = self.policy["humans"]["antropophag"]["idpEnrollment"]
        assert enrollment["nativeCreateUser"]
        assert not enrollment["passwordAssigned"]
        assert not enrollment["mfaEnrolled"]
        assert not enrollment["customActivationFlow"]
        assert not enrollment["activationLinkIssued"]
        assert not (ROOT / "deploy/identity/existing-user-activation.json").exists()
        assert self.people["antropophag"]["idpUserUuid"] == "6015c85b-82e9-49ce-a4e3-0270c676e26d"

    def test_native_rancher_replacement_preserves_retired_identity_and_grants(self):
        rancher = self.policy["humans"]["antropophag"]["rancher"]
        assert rancher["nativePrincipalIsImmutable"]
        assert not rancher["retiredExternalUserEnabled"]
        assert rancher["currentExternalUserId"] == self.people["antropophag"]["rancherOidcUserId"]
        assert self.people["antropophag"]["rancherBindingPrefix"] == "identity-tim-v2-"
        assert rancher["retainDisabledLegacyRecordAndInertGrantHistory"]

    def test_umami_is_explicitly_suspended_not_false_oidc_success(self):
        target = self.policy["humans"]["antropophag"]["umami"]
        assert target["state"] == "suspended-pending-native-oidc"
        assert target["softDisabledWithoutDeletingData"]
        assert target["gatePlusNativePasswordIsNotOidc"]
        # Umami is suspended pending native OIDC, tracked in follow-up issue 85.
        follow_up_issue = 85
        assert target["followUpIssue"] == follow_up_issue


if __name__ == "__main__":
    unittest.main()
