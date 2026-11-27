import copy

import pytest

from ci.quality.public_http01_generation import same_presentation


def fixture(uid):
    ns, name, host = "owner", "challenge", "probe.invalid"
    owner = {
        "apiVersion": "acme.cert-manager.io/v1",
        "kind": "Challenge",
        "name": name,
        "uid": uid,
        "controller": True,
    }
    token = "A" * 43
    challenge = {
        "apiVersion": owner["apiVersion"],
        "kind": "Challenge",
        "metadata": {"namespace": ns, "name": name, "uid": uid},
        "spec": {"dnsName": host, "type": "HTTP-01", "token": token},
        "status": {"state": "pending", "presented": True, "processing": True},
    }
    children = [
        {
            "apiVersion": api,
            "kind": kind,
            "metadata": {
                "name": n,
                "uid": uid + "-" + n,
                "namespace": ns,
                "ownerReferences": [copy.deepcopy(owner)],
            },
        }
        for api, kind, n in [
            ("networking.k8s.io/v1", "Ingress", "ing"),
            ("v1", "Service", "svc"),
            ("v1", "Pod", "pod"),
        ]
    ]
    children[0]["metadata"]["labels"] = {"homelab.alchemmist.xyz/public-web": "true"}
    children[0]["spec"] = {
        "ingressClassName": "traefik",
        "rules": [
            {
                "host": host,
                "http": {
                    "paths": [
                        {
                            "path": "/.well-known/acme-challenge/" + token,
                            "pathType": "ImplementationSpecific",
                            "backend": {
                                "service": {"name": "svc", "port": {"number": 8089}}
                            },
                        }
                    ]
                },
            }
        ],
    }
    return (ns, name, uid, host), challenge, *children


@pytest.mark.parametrize("index", [2, 3, 4])
def test_same_name_recreation_never_reuses_an_old_child(index):
    before = fixture("first")
    after = list(fixture("next"))
    assert same_presentation(*before) and same_presentation(*after)
    after[index] = before[index]
    assert not same_presentation(*after)
    assert not same_presentation(before[0], *after[1:])
    assert not same_presentation(after[0], None, *before[2:])


@pytest.mark.parametrize(
    "fault",
    [
        "deleting",
        "valid",
        "not-presented",
        "other-name",
        "other-peer",
        "token",
        "extra-path",
        "extra-controller",
        "class",
        "selector",
        "other-service",
        "other-port",
        "default",
    ],
)
def test_inactive_or_unrelated_observations_cannot_present(fault):
    expected, ch, ing, svc, pod = fixture("current")
    r = ing["spec"]
    path = r["rules"][0]["http"]["paths"][0]
    if fault == "deleting":
        ch["metadata"]["deletionTimestamp"] = "deleting"
    elif fault == "valid":
        ch["status"]["state"] = "valid"
    elif fault == "not-presented":
        ch["status"]["presented"] = False
    elif fault == "other-name":
        ch["spec"]["dnsName"] = "else.invalid"
    elif fault == "other-peer":
        pod["metadata"]["namespace"] = "other"
    elif fault == "token":
        path["path"] += "x"
    elif fault == "extra-path":
        r["rules"][0]["http"]["paths"].append(path.copy())
    elif fault == "extra-controller":
        svc["metadata"]["ownerReferences"] *= 2
    elif fault == "class":
        r["ingressClassName"] = "private"
    elif fault == "selector":
        ing["metadata"]["labels"] = {}
    elif fault == "other-service":
        path["backend"]["service"]["name"] = "other"
    elif fault == "other-port":
        path["backend"]["service"]["port"]["number"] = 80
    else:
        r["defaultBackend"] = {}
    assert not same_presentation(expected, ch, ing, svc, pod)
