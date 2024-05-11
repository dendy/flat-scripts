#!/usr/bin/env python3

import sys
sys.dont_write_bytecode = True

import glob
import os
import stat


DefaultExcludeFileNames = ['.git']


# Class which validates whether specific file path exists under any of the the
# subpaths root_dir/@subpaths.
#
# Paths may be given in next formats relative to the @root_dir:
#   - some/subpath/foo
#         Full path means single exact file.
#   - some/subpath/foo/
#         Forward slash (/) at the end means include everything from this
#         folder.
#   - some/**/*.cpp
#         Star (*) anywhere in the path means use Python glob format.

class PathMatcher:
	def __init__(self, root_dir, subpaths):
		prefixes = list()
		files_set = set()

		if not root_dir is None:
			root_dir = os.path.realpath(os.path.abspath(root_dir))

		if subpaths is None:
			subpaths = []
		elif type(subpaths) != list:
			subpaths = [subpaths]

		for subpath in subpaths:
			#print(f'subpath={subpath};')
			if root_dir is None:
				abs_subpath = subpath
			else:
				abs_subpath = f'{root_dir}/{subpath}'
			if '*' in subpath:
				wild_list = glob.glob(abs_subpath, recursive=True)
				wild_set = set()
				wild_links = set()

				def is_link_prefixed(path):
					nonlocal wild_links
					for wild_link in wild_links:
						if wild_file.startswith(wild_link):
							return True
					return False

				for wild_file in wild_list:
					st_mode = os.stat(wild_file, follow_symlinks=False).st_mode
					if stat.S_ISDIR(st_mode): continue
					if stat.S_ISLNK(st_mode):
						print(f'link: {wild_file}')
						wild_links.add(wild_file)
						continue
					if stat.S_ISCHR(st_mode): continue
					if stat.S_ISBLK(st_mode): continue
					if not stat.S_ISREG(st_mode): continue
					if is_link_prefixed(wild_file): continue
					if root_dir is None:
						wild_set.add(wild_file)
					else:
						print(f'add: {wild_file}')
						wild_set.add(os.path.relpath(wild_file, root_dir))
				files_set.update(wild_set)
			elif os.path.isdir(abs_subpath):
				if root_dir is None:
					prefixes.append(f'{abs_subpath}/')
				else:
					prefixes.append(f'{subpath}/')
			else:
				if root_dir is None:
					files_set.add(abs_subpath)
				else:
					files_set.add(subpath)

		self.prefixes = prefixes
		self.files_set = files_set
		self.files = list(files_set)

	def from_rel_dir(root_dir, subpaths):
		return PathMatcher(root_dir, subpaths)

	def from_abs_dir(subpaths):
		return PathMatcher(None, subpaths)

	def matches(self, path):
		for prefix in self.prefixes:
			if path.startswith(prefix):
				return True
		return path in self.files


# Replacement for the glob.glob()
# Returns all the regular non symlink files under the @root_dir.
# @exclude_file_names may optionally include list of full case-sensitive file
# names to exclude, default: ['.git']

def find_unique_paths(root_dir, exclude_file_names=DefaultExcludeFileNames):
	real_dir = os.path.realpath(root_dir)

#	if exclude is None:
#		exclude = []
#	elif type(exclude) is str:
#		exclude = [exclude]
#	elif type(exclude) == list:
#		exclude = [os.path.realpath(e) for e in exclude]
#	else:
#		raise AttributeError(f'Invalid exclude: {type(exclude)}')

#	def is_excluded(file):
#		for e in exclude:
#			if file.startswith(e):
#				return True
#		return False

	paths = []

#	rest_paths = []

	def scan_path(dir_path):
		def make_info(file_name):
			if dir_path == '.':
				file_path = file_name
			else:
				file_path = f'{dir_path}/{file_name}'
			full_path = f'{real_dir}/{file_path}'
			st = os.stat(full_path, follow_symlinks=False)
			return file_name, file_path, full_path, st.st_mode

		def is_excluded(file_name):
			return file_name in exclude_file_names

		file_names = sorted(os.listdir(f'{real_dir}/{dir_path}'))
#		print(f'{dir_path} -> {file_names}')
		file_infos = [make_info(f) for f in file_names if not is_excluded(f)]
		for file_info in file_infos:
			file_name, file_path, full_path, st_mode = file_info
			if stat.S_ISDIR(st_mode):
				scan_path(file_path)
		for file_info in file_infos:
			file_name, file_path, full_path, st_mode = file_info
			if not stat.S_ISDIR(st_mode):
#				print(f'{file_name} {stat.S_ISLNK(st_mode)} {stat.S_ISCHR(st_mode)} {stat.S_ISBLK(st_mode)} {stat.S_ISREG(st_mode)}')
				if not stat.S_ISLNK(st_mode) and not stat.S_ISCHR(st_mode) and not stat.S_ISBLK(st_mode) and stat.S_ISREG(st_mode):
					paths.append(file_path)
#				else:
#					rest_paths.append(file_path)

	scan_path('.')

#	for rest_path in rest_paths:
#		print(f'rest: {rest_path}')

	return paths


if __name__ == '__main__':
	import argparse
	import glob

	parser = argparse.ArgumentParser()
	parser.add_argument('--glob', action='store_true')
	parser.add_argument('-v', '--verbose', action='count')
	parser.add_argument('path')
	args = parser.parse_args()

	if args.glob:
		glob_paths = glob.glob(f'{args.path}/**/**', recursive=True)
		glob_paths += glob.glob(f'{args.path}/**/.**', recursive=True)
		glob_paths += glob.glob(f'{args.path}/**/.**/**', recursive=True)
		unique = set()
		for path in glob_paths:
			if not os.path.isfile(path): continue
			unique.add(os.path.realpath(path))
		paths = sorted(list(unique))
		paths = [f'{os.path.relpath(f, args.path)}' for f in paths]
	else:
		paths = find_unique_paths(args.path)

	print(len(paths))

	if args.verbose:
		paths = sorted(paths)
		for f in paths:
			print(f)
