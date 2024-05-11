#!/usr/bin/env python3

import sys
sys.dont_write_bytecode = True

import argparse
import os
import subprocess


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--name', required=True)
	parser.add_argument('--email', required=True)
	parser.add_argument('--time', default='T13:00+00')
	parser.add_argument('--amend', action='store_true')
	parser.add_argument('date')
	args, extra = parser.parse_known_args()

	name = args.name
	email = args.email
	date = f'{args.date}{args.time}'

	env = os.environ
	env['GIT_AUTHOR_NAME'] = name
	env['GIT_AUTHOR_EMAIL'] = email
	env['GIT_AUTHOR_DATE'] = date
	env['GIT_COMMITTER_NAME'] = name
	env['GIT_COMMITTER_EMAIL'] = email
	env['GIT_COMMITTER_DATE'] = date

	if args.amend:
		git_args = ['--amend', '-C', 'HEAD', '--reset-author']
	else:
		git_args = []

	subprocess.run(['git', 'commit', *git_args, *extra], env=env, check=True)


if __name__ == '__main__':
	main()
