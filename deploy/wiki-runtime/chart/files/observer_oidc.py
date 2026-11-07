"""Preserve the pinned image's complete native OIDC implementation; add freshness."""
import importlib.util
import sys
from observer_membership import install_wiki_guard

spec = importlib.util.spec_from_file_location('wiki_native_oidc', '/observer-native/oidc.py')
native = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = native
spec.loader.exec_module(native)


def configure_store(store):
    native.configure_store(store)
    install_wiki_guard(store)


def __getattr__(name):
    return getattr(native, name)
