#!/usr/bin/env python3

import sys
sys.dont_write_bytecode = True

import yaml
import os.path
import fnmatch
import glob
import argparse

import utils


def user_expanded_value(value):
	if value.startswith('~'):
		return os.path.expanduser(value)
	else:
		return value


def run(config_path, root_dir, project_dir, local_path=None, variants=None):
	config_path = os.path.realpath(config_path)
	root_dir = os.path.realpath(root_dir)

	platform_name_for_sys_platform = dict(
		linux  = 'linux',
		win32  = 'win',
		darwin = 'mac',
	)
	platform_name = platform_name_for_sys_platform[sys.platform]

	def check_valid_platform_name(name):
		for value in platform_name_for_sys_platform.values():
			if name == value: return
		raise AttributeError(f'Invalid platform name: {name}')

	#def get_platform_paths(d):
		## check that all keys in the d are valid platform names
		#for key in d.keys():
			#check_valid_platform_name(key)
		#paths = d.get(platform_name)
		#if paths is None: paths = []
		#return paths

	with open(config_path, 'r') as f:
		config = yaml.load(f, Loader=yaml.FullLoader)

	name = config['name']

	config_variants = config.get('variants', [])
	for variant in variants:
		if variant not in config_variants:
			raise AttributeError(f'Invalid variant: {variants} Allowed variants: {config_variants}')

	def get_local():
		if not local_path is None:
			with open(local_path, 'r') as f:
				mappings = yaml.load(f, Loader=yaml.FullLoader)
				if mappings is None:
					mappings = dict()
				if type(mappings) != dict:
					raise AttributeError(f'Invalid local config yaml: {type(mappings)}')
				config = mappings.pop('config', None)
				if config is not None and type(config) != dict:
					raise AttributeError('config in local conf must be a dict ({type(config)})')
				mappings = {key: user_expanded_value(value) for key, value in mappings.items()}
		else:
			mappings = dict()
			config = None
		mappings['config_dir'] = os.path.dirname(config_path)
		return config, mappings

	local_config, local_mappings = get_local()

	os.makedirs(project_dir, exist_ok=True)

	def get_object(key, required):
		nonlocal config
		nonlocal local_config
		if required:
			c = config[key]
		else:
			c = config.get(key)
		if local_config is None:
			l = None
		else:
			l = local_config.get(key)
		return c, l

	def get_array(key, required):
		c, l = get_object(key, required)
		if c is None and l is None: return
		if c is None: c = []
		if not l is None:
			c += l
		return c

	def get_dict(key, required):
		c, l = get_object(key, required)
		if c is None and l is None: return
		if c is None: c = dict()
		if not l is None:
			c.update(l)
		return c

	with open(f'{project_dir}/{name}.creator', 'w') as f:
		print('[General]', file=f)

	with open(f'{project_dir}/{name}.cflags', 'w') as f:
		cflags = get_array('cflags', False)
		if not cflags is None:
			print(' '.join(cflags), file=f)

	with open(f'{project_dir}/{name}.cxxflags', 'w') as f:
		cxxflags = get_array('cxxflags', False)
		if not cxxflags is None:
			print(' '.join(cxxflags), file=f)

	def process_macros(macros, stack):
		nonlocal f, variants, config_variants

		print(file=f)
		if stack:
			name = '/'.join(stack)
		else:
			name = 'common'
		print(f'// {name}', file=f)

		for key, value in macros.items():
			value_type = type(value)
			if value is None:
				print(f'#define {key}', file=f)
			elif value_type == int:
				print(f'#define {key} {value}', file=f)
			elif value_type == str:
				print(f'#define {key} {value}', file=f)
			elif value_type == dict:
				if key not in config_variants:
					raise AttributeError(f'Invalid macro variant: {key} Allowed variants: {config_variants}')
				if key in variants:
					process_macros(value, [*stack, key])
			else:
				raise AttributeError(f'Invalid macro type: key={key} value={value} type={value_type}')

	def process_undef(macros, stack):
		nonlocal f, variants, config_variants

		print(file=f)
		if stack:
			name = '/'.join(stack)
		else:
			name = 'common'
		print(f'// {name}', file=f)

		for key, value in macros.items():
			value_type = type(value)
			if value is None:
				print(f'#undef {key}', file=f)
			elif value_type == dict:
				if key not in config_variants:
					raise AttributeError(f'Invalid macro variant: {key} Allowed variants: {config_variants}')
				if key in variants:
					process_undef(value, [*stack, key])
			else:
				raise AttributeError(f'Invalid macro type: key={key} value={value} type={value_type}')

	with open(f'{project_dir}/{name}.config', 'w') as f:
		macros = get_dict('macros', False)
		if not macros is None:
			process_macros(macros, [])

		undef = get_dict('undef', False)
		if not undef is None:
			process_undef(undef, [])

	def expand_path_mappings(expanded_path):
		nonlocal local_mappings
		mapped_expanded_path = expanded_path
		for key, value in local_mappings.items():
			mapped_expanded_path = mapped_expanded_path.replace(f'${key}', value)
		if '$' in mapped_expanded_path:
			print(f'WARNING: Path not fully expanded: {expanded_path}', file=sys.stderr)
			return expanded_path
		return mapped_expanded_path

	def expand_path_norm(path):
		nonlocal root_dir
		expanded_path = os.path.expanduser(path)
		mapped_expanded_path = expand_path_mappings(expanded_path)
		if os.path.isabs(mapped_expanded_path):
			real_mapped_expanded_path = os.path.realpath(mapped_expanded_path)
			return real_mapped_expanded_path
		else:
			real_mapped_expanded_path = os.path.realpath(f'{root_dir}/{mapped_expanded_path}')
			rp = os.path.relpath(real_mapped_expanded_path, root_dir)
			if rp.startswith('../'):
				return real_mapped_expanded_path
			else:
				return rp

	def expand_path_abs(path):
		nonlocal root_dir
		expanded_path = os.path.expanduser(path)
		mapped_expanded_path = expand_path_mappings(expanded_path)
		if not os.path.isabs(mapped_expanded_path):
			mapped_expanded_path = f'{root_dir}/{mapped_expanded_path}'
		return os.path.realpath(mapped_expanded_path)

	def process_include(include):
		if type(include) != str:
			raise AttributeError(f'Invalid entry: {include}')
		expanded_include = expand_path_abs(include)
		print(expanded_include, file=f)
		if not os.path.isdir(expanded_include):
			print(f'WARNING: Include does not exist: {expanded_include}')

	def process_includes(includes, allow_variants):
		if includes is None: return
		if type(includes) != list:
			raise AttributeError(f'Invalid includes type: {type(includes)}')
		for include in includes:
			if type(include) == dict:
				if not allow_variants:
					raise AttributeError(f'Invalid includes variant')
				for key, value in include.items():
					if not key in config_variants:
						raise AttributeError(f'Invalid include variant: {key}')
					if key in variants:
						process_includes(value, False)
			else:
				process_include(include)

	with open(f'{project_dir}/{name}.includes', 'w') as f:
		includes = get_array('includes', False)
		if not includes is None:
			process_includes(includes, True)
		includes = get_array(f'{platform_name}_includes', False)
		if not includes is None:
			process_includes(includes, True)

			#for include in includes:
##				print(include)
				#if type(include) == dict:
					#for platform_include in get_platform_paths(include):
						#process_include(platform_include)
				#else:
					#process_include(include)

	ignores = get_array('ignore', False)
	def is_ignored(path):
		nonlocal ignores
		if ignores is None: return False
		for i in ignores:
			if fnmatch.fnmatchcase(path, i): return True
		return False

	abs_excludes = []
	rel_excludes = []

	excludes = get_array('exclude', False)
	if not excludes is None:
		for exclude in excludes:
			expanded_exclude = expand_path_norm(exclude)
			print(f'exclude={exclude}; expanded_exclude={expanded_exclude};')
			if os.path.isabs(expanded_exclude):
				abs_excludes.append(expanded_exclude)
			else:
				rel_excludes.append(expanded_exclude)

	abs_exclude_path_matcher = utils.PathMatcher.from_abs_dir(abs_excludes)
	rel_exclude_path_matcher = utils.PathMatcher.from_rel_dir(root_dir, rel_excludes)

	with open(f'{project_dir}/{name}.files', 'w') as f:
		for path in get_array('files', True):
			print(file=f)
			print(f'# {path}', file=f)
			expanded_path = expand_path_norm(path)

			is_abs = os.path.isabs(expanded_path)
			#print(f'expanded_path={expanded_path}; is_abs={is_abs};')

			if is_abs:
				abs_expanded_path = expanded_path
				exclude_path_matcher = abs_exclude_path_matcher
				path_matcher = utils.PathMatcher.from_abs_dir(expanded_path)
			else:
				abs_expanded_path = f'{root_dir}/{expanded_path}'
				exclude_path_matcher = rel_exclude_path_matcher
				#print(f'from_rel_dir({root_dir}, {expanded_path})')
				path_matcher = utils.PathMatcher.from_rel_dir(root_dir, expanded_path)

			if path_matcher.prefixes:
				#print(f'abs_expanded_path={abs_expanded_path};')
				files = [os.path.normpath(f'{expanded_path}/{file_path}') for file_path in utils.find_unique_paths(abs_expanded_path)]
			else:
				print('no path_matcher.prefixes')
				files = path_matcher.files

			total_count = 0
			added_count = 0
			for fp in files:
				total_count += 1
				if is_ignored(fp):
					continue
				if exclude_path_matcher.matches(fp):
					continue
				if is_abs:
					abs_fp = fp
				else:
					abs_fp = f'{root_dir}/{fp}'
				print(abs_fp, file=f)
				added_count += 1

			if total_count == 0:
				print(f'WARNING: Path does not have files: {expanded_path}')


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--config', required=True)
	parser.add_argument('--root-dir', required=True)
	parser.add_argument('--project-dir', required=True)
	parser.add_argument('--local')
	parser.add_argument('variants', nargs='*', default=[])
	args = parser.parse_args();

	run(args.config, args.root_dir, args.project_dir, args.local, args.variants)


if __name__ == '__main__':
	main()
