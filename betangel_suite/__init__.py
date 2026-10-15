"""betangel-suite: Yu's offline Betfair replay and paper-trading suite (docs/DESIGN.md).

Importing this package imports nothing else. Every process starts through bin/suite, which arms
betangel_suite.guard before any betangel_research module is loaded; betangel_suite.rx is the only
module that imports betangel_research.
"""
