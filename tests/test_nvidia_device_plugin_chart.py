"""Offline render contract for the GPU device-plugin chart."""

import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("helm"), "helm unavailable")
class NvidiaDevicePluginChartTests(unittest.TestCase):
    """Verify the DaemonSet retains its real kubelet registration contract."""

    def test_render_preserves_registration_and_gpu_runtime(self) -> None:
        import yaml

        result = subprocess.run(
            [
                "helm",
                "template",
                "nvidia-device-plugin",
                "charts/nvidia-device-plugin",
                "--namespace",
                "kube-system",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        [daemonset] = [
            doc for doc in yaml.safe_load_all(result.stdout) if doc is not None
        ]
        self.assertEqual(daemonset["kind"], "DaemonSet")
        self.assertEqual(daemonset["metadata"]["namespace"], "kube-system")
        pod_spec = daemonset["spec"]["template"]["spec"]
        self.assertEqual(pod_spec["runtimeClassName"], "nvidia")
        self.assertFalse(pod_spec["automountServiceAccountToken"])
        [container] = pod_spec["containers"]
        # v0.20.2 is the owner-published, cluster-verified plugin tag (main
        # 20721c33). nvcr.io rejects anonymous manifest reads, so the OCI
        # digest stays owner-supply evidence; assert the exact identity so
        # no latest/unqualified drift slips in instead.
        self.assertEqual(
            container["image"], "nvcr.io/nvidia/k8s-device-plugin:v0.20.2"
        )
        [mount] = container["volumeMounts"]
        self.assertEqual(mount["mountPath"], "/var/lib/kubelet/device-plugins")
        self.assertFalse(mount.get("readOnly", False))
        [volume] = pod_spec["volumes"]
        self.assertEqual(
            volume["hostPath"],
            {"path": "/var/lib/kubelet/device-plugins", "type": "Directory"},
        )


if __name__ == "__main__":
    unittest.main()
