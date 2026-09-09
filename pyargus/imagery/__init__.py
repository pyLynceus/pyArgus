"""Cameras, projection and colorization: lidar meets the imagery.

The bridge from pyLynceus (or any LP360-style EO delivery) into the
cloud: formats.eo reads where each photo was taken from and which way
it looked; imagery.camera projects ground points into stored pixels
through a calibrated Brown-Conrady lens; imagery.colorize picks the
best photo per point, checks the cloud itself for occlusion, samples
the JPEGs and fills the LAS RGB fields.

Reading images needs Pillow -- ``pip install pyargus[imagery]``.
Everything else here is numpy arithmetic.
"""
