# defusedxml
#
# Copyright (c) 2013 by Christian Heimes <christian@python.org>
# Licensed to PSF under a Contributor Agreement.
# See https://www.python.org/psf/license for licensing details.
"""Defuse XML bomb denial of service vulnerabilities
"""
from __future__ import print_function, absolute_import

from .common import (
    DefusedXmlException,
    DTDForbidden,
    EntitiesForbidden,
    ExternalReferenceForbidden,
    NotSupportedError,
)


def defuse_stdlib():
    """Geo360View同梱版ではElementTreeだけを利用する。"""
    raise NotSupportedError("Geo360View bundles only defusedxml.ElementTree")


__version__ = "0.7.1"

__all__ = [
    "DefusedXmlException",
    "DTDForbidden",
    "EntitiesForbidden",
    "ExternalReferenceForbidden",
    "NotSupportedError",
]
