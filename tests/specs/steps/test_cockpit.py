"""No step code. That is the claim this file exists to make.

Every line of `cockpit.feature` is either the provisioning step or one of the read-and-compare
steps ATF registers, so a feature testing ATF's own front end needs nothing but a binding.
"""

from pytest_bdd import scenarios

scenarios("../features/cockpit.feature")
