#!/usr/bin/env python3

import argparse
import os.path
import subprocess
import yaml

# Assuming next typical folder structure:
#   root_dir           - very root
#     src_dir          - code from source control,
#                        paths in config file will be relative to the src_dir
#       ide_config_dir - creator ide config files
#     local_dir        - local user configuration
#       local.yaml
#     project_dir      - where QtCreator .creator project file is generated
#     build_dir        - build dir location

root_dir = os.path.abspath(f'{__file__}/../..')
src_dir = os.path.abspath(f'{root_dir}/src_dir')
project_dir = os.path.abspath(f'{root_dir}/project_dir')
local_yaml = f'{root_dir}/local_dir/local.yaml'

with open(local_yaml, 'r') as f:
	flat_scripts_dir = yaml.load(f, Loader=yaml.FullLoader)['flat_scripts_dir']

subprocess.run([f'{flat_scripts_dir}/generate-qtproject.py',
	'--config',      f'{src_dir}/ide_config_dir/config.yaml',
	'--root-dir',    src_dir,
	'--project-dir', project_dir,
	'--local',       local_yaml],
	check=True)
