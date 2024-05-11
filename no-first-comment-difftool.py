#!/usr/bin/env python3

import sys
sys.dont_write_bytecode = True

import argparse
import os
import subprocess
import tempfile
import time

import utils


def detect_comment_mode(path, input_file):
	try:
		for line in input_file:
			line = line.strip()
			l = len(line)
			#print(f'line={line}')

			if l == 0: continue

			if line.startswith('#'):
				return 1

			if line.startswith('//'):
				return 2

			if line.startswith('/*'):
				return 3

			return 0

		return 0
	except UnicodeDecodeError:
		print(f'detect_comment_mode: Invalid unicode file: {path}')
		return 0


def detect_oneline_comment_n(input_file, prefix, max_line_breaks):
	n = 0
	lb = 0
	lbn = 0
	for line in input_file:
		line = line.strip()
		#print(f'sl={line}')
		if len(line) == 0:
			if lbn == 0:
				if lb == max_line_breaks:
					break
				lb += 1
				lbn += 1
			else:
				lbn += 1
		else:
			if not line.startswith(prefix):
				break
			n += lbn
			lbn = 0
			n += 1
	return n


def detect_shell_comment_n(input_file):
	return detect_oneline_comment_n(input_file, '#', 1)


def detect_oneline_c_comment_n(input_file):
	return detect_oneline_comment_n(input_file, '//', 1)


def detect_multiline_c_comment_n(path, input_file):
	try:
		def find_begin(line):
			try:
				pos = line.index('/*')
				if pos != 0:
					raise AttributeError(f'Comment begin pos is not at BOL: {path}')
				return True
			except ValueError:
				return False

		def find_end(line):
			try:
				pos = line.index('*/')
				if pos != len(line) - 2:
					raise AttributeError(f'Comment end pos is not at EOL: {path}')
				return True
			except ValueError:
				return False

		n = 0
		has_begin = False
		has_end = False
		for line in input_file:
			line = line.strip()

			if has_begin:
				n += 1
				if not find_end(line):
					continue
				has_end = True
				break
			if len(line) == 0:
				n += 1
				continue
			if not find_begin(line):
				break
			has_begin = True
			n += 1
			if find_end(line[2:]):
				has_end = True
				break

		if not has_begin or not has_end:
			raise AttributeError(f'detect_multiline_c_comment_n: Invalid multiline comment: {path}')

		return n
	except AttributeError:
		return 0


def detect_comment_n(path, input_file):
	mode = detect_comment_mode(path, input_file)
	#print(f'mode={mode}')

	if mode == 0:
		return 0

	input_file.seek(0)

	if mode == 1:
		return detect_shell_comment_n(input_file)

	if mode == 2:
		return detect_oneline_c_comment_n(input_file)

	if mode == 3:
		return detect_multiline_c_comment_n(path, input_file)


def remove_file_prefix(path, input_file, output_file, remove_n, add_n):
#	print(f'{path} {remove_n}')

	if remove_n != 0:
		i = 0
		for line in input_file:
			i += 1
			if i == remove_n:
				break

	for i in range(add_n):
		output_file.write('\n')

	try:
		for line in input_file:
			output_file.write(line)
	except UnicodeDecodeError:
		print(f'remove_file_prefix: Invalid unicode file: {path}')
		raise


def compare_files(a_path, b_path, a_conv_path, b_conv_path):
	cli = ['diff', '--color=always', a_conv_path, b_conv_path]
	ps = subprocess.run(cli, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=False)
	if len(ps.stdout) != 0:
		print(f'{a_path}    ->    {b_path}')
		sys.stdout.buffer.write(ps.stdout)
	if ps.returncode == 1:
		return

	if ps.returncode != 0:
		print(f'differr: ({ps.returncode}) {ps.stderr}')
		print(f'cli: {" ".join(cli)}')
		time.sleep(1000)


def convert_all(root_dir):
	if os.path.isfile(root_dir):
		all_paths = [os.path.realpath(root_dir)]
	else:
		all_paths = utils.find_unique_paths(root_dir, '.git/')
#	print(f'all_paths={all_paths}')

	for path in all_paths:
		tmp_path = f'{path}.tmp-no-first-comment'

		converted = False

		with open(path) as input_file:
			n = detect_comment_n(path, input_file)
			if n == 0: continue

			input_file.seek(0)

			try:
				with open(tmp_path, 'w') as output_file:
					remove_file_prefix(path, input_file, output_file, n, 0)
					converted = True
			except UnicodeDecodeError:
				os.remove(tmp_path)

		if converted:
			perms = os.stat(path).st_mode
			os.remove(path)
			os.rename(tmp_path, path)
			os.chmod(path, perms)


def convert_difftool(a_path, b_path=None, base_path=None):
	#print(f'a_path={a_path} b_path={b_path}')

	if b_path is None:
		with open(a_path) as f:
			a_n = detect_comment_n(a_path, f)
			print(f'a_n={a_n}')

			f.seek(0)

			with open('/home/dlevin/projects/mali400/tmp/out.txt', 'w') as of:
				remove_file_prefix(a_path, f, of, a_n, 15)
	else:
		with open(a_path) as a_input_file:
			with open(b_path) as b_input_file:
				a_n = detect_comment_n(a_path, a_input_file)
				b_n = detect_comment_n(b_path, b_input_file)

				#print(f'a_n={a_n} b_n={b_n}')

				if a_n == 0 and b_n == 0:
					return compare_files(a_path, b_path, a_path, b_path)

				try:
					max_n = max(a_n, b_n)
				except TypeError:
					print('oooops')

				a_input_file.seek(0)
				b_input_file.seek(0)

				with tempfile.NamedTemporaryFile(mode='w') as a_output_file:
					with tempfile.NamedTemporaryFile(mode='w') as b_output_file:
						remove_file_prefix(a_path, a_input_file, a_output_file, a_n, max_n)
						remove_file_prefix(b_path, b_input_file, b_output_file, b_n, max_n)

						a_output_file.seek(0)
						b_output_file.seek(0)

						return compare_files(a_path, b_path, a_output_file.name, b_output_file.name)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--convert')
	parser.add_argument('--difftool', nargs='*')
	args = parser.parse_args()

	if not args.convert is None:
		return convert_all(args.convert)

	if not args.difftool is None:
		return convert_difftool(*args.difftool)


if __name__ == '__main__':
	main()
