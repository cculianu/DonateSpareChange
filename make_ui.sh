#!/bin/bash

uic="pyuic5"

echo "$uic ui.ui"
$uic ui.ui | sed 's/^import resources_rc/from . import resources/' > DonateSpareChange/ui.py
