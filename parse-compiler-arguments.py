#!/usr/bin/env python3

import sys
sys.dont_write_bytecode = True

import argparse
import os.path


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--ide', action='store_true')
	parser.add_argument('--curdir')
	args, extra = parser.parse_known_args()

	if args.curdir is None:
		curdir = None
	else:
		curdir = args.curdir
		if not curdir.endswith('/'):
			curdir += '/'

	includes = set()
	system_includes = set()
	defines = dict()
	undefs = set()
	others = set()

	i = 0

	opt_infos = {
		'-o':  1,
		'-MF': 1,
	}

	def get_next():
		nonlocal i
		if i == len(extra):
			raise AttributeError('Not enough arguments')
		value = extra[i]
		i += 1
		return value

	def rel_include(include):
		if curdir is None or not include.startswith(curdir):
			return include
		else:
			return include[len(curdir):]

	while i < len(extra):
		e = extra[i]
		i += 1

		if e.startswith('-I'):
			if len(e) == 2:
				include = get_next()
			else:
				include = e[2:]
			include = rel_include(include)
			includes.add(include)
			continue

		if e == '-isystem':
			include = get_next()
			include = rel_include(include)
			system_includes.add(include)
			continue

		if e.startswith('-D'):
			if len(e) == 2:
				define = get_next()
			else:
				define = e[2:]
			key_value = define.split('=', maxsplit=1)
			if len(key_value) == 1:
				key = define
				value = None
			else:
				key, value = key_value
			defines[key] = value
			continue

		opt_info = opt_infos.get(e)
		if opt_info is None:
			others.add(e)
		else:
			opt_args = [get_next() for opt_i in range(opt_info)]
			others.add(f'{e} {" ".join(opt_args)}')

	if args.ide:
		if includes:
			print()
			includes_list = sorted(list(includes))
			print(f'Includes: {len(includes_list)}')
			print()
			for include in includes_list:
				print(f'  - {os.path.normpath(include)}')

		if system_includes:
			print()
			includes_list = sorted(list(system_includes))
			print(f'System Includes: {len(includes_list)}')
			print()
			for include in includes_list:
				print(f'  - {os.path.normpath(include)}')

		if defines:
			print()
			key_list = sorted(defines.keys())
			print(f'Defines: {len(key_list)}')
			print()
			max_key_len = 0
			for key in key_list:
				value = defines[key]
				if value is None:
					print(f'  {key}:')
				else:
					print(f'  {key}: {value}')
	else:
		if includes:
			print()
			includes_list = sorted(list(includes))
			print(f'Includes: {len(includes_list)}')
			for include in includes_list:
				print(f'    {include}')

		if system_includes:
			print()
			includes_list = sorted(list(system_includes))
			print(f'System Includes: {len(includes_list)}')
			for include in includes_list:
				print(f'    {include}')

		if defines:
			print()
			key_list = sorted(defines.keys())
			print(f'Defines: {len(key_list)}')
			max_key_len = 0
			for key in key_list:
				max_key_len = max(max_key_len, len(key))
			for key in key_list:
				value = defines[key]
				if value is None:
					print(f'    {key}')
				else:
					print(f'    {key:<{max_key_len}} = {value}')

		if others:
			print()
			others_list = sorted(list(others))
			print(f'Other arguments: {len(others_list)}')
			for other in others_list:
				print(f'    {other}')


if __name__ == '__main__':
	main()
