#!/usr/bin/env python3

import sys
sys.dont_write_bytecode = True

import argparse
from dataclasses import dataclass
import enum
import glob
import hashlib
import os.path
import shutil
import stat
import subprocess
import tempfile
import yaml

import utils


# Helper script tp cleanup source code.
#
# We define multiple steps to cleanup any source code as:
#
# 1. Fix corrupted or mixed encoding in text files.
#
#    These are clear bugs in source code files, typically a result of
#    simultaneous usage of various editors, tools by different users, which
#    contribute to the fix content without checking for the consistency.
#
#    Corrupted encoding may only be resolved and validated by a human, because
#    there is no streightforward solution how particular invalid encoding
#    character should be fixed.
#
#    This script only helps to identify corrupted files.
#
# 2. Convert all the text files into UTF-8.
#
#    UTF-8 obsoleted all other multibyte encodings, providing unified encoding
#    for the text files. All the source code should be converted into the UTF-8
#    as an early step, before doing anything else.
#
#    $ cleanup-sources.py --utf <path>
#
#    Command will tell whether any files have been successfully converted into
#    UTF-8.
#
#    In case any corrupted encoding will be detected command will do no changes
#    and display list of broken files instead. User should manually inspect
#    those and make manual fixes.
#
# 3. Fix line breaks to the UNIX format (\n) and remove trailing whitespaces.
#
#    Line break does not represent printing format anymore with caracter return
#    or other printing instructions. In source code line break separates lines.
#
#    $ cleanup-sources.py --eol <path>
#
#    Command will tell whether any EOL have been fixed. You can verify that
#    only EOL changes have been made with:
#
#    $ git diff --ignore-space-at-eol
#
# 4. Fix wrong executable permissions.
#
#    Usually a result of submitting files from Windows file system, they might
#    retain executable permission by mistake.
#
#    $ cleanup-sources.py --exe <path>
#
# 5. (optional) Remove license headers
#
#    License headers are not a part of the source code, but sometimes added at
#    the top of the file, instead of keeping license in the separate file.
#    Such headers cause problems when tracking the changes between project
#    revisions.
#
#    $ cleanup-sources.py --lic <path>


@dataclass
class FileInfo:
	path: str
	mime_type: str
	charset: str
	st_mode: int


class LinePrinter:
	def __init__(self):
		self.has_line = False

	def print(self, final=False):
		self.clear()
		self.has_line = True
		self.printer()
		if final:
			print()
		sys.stdout.flush()

	def clear(self):
		if self.has_line:
			print('\033[1K\r', end='')
			sys.stdout.flush()


class PathMatcher:
	def __init__(self, abs_path, project_root, paths):
		self.abs_path = abs_path
		self.project_root = project_root
		self.prefixes = []
		self.files = []

		if paths is None:
			paths = []
		elif type(paths) != list:
			paths = [paths]

		for path in paths:
			if path.endswith('/'):
				self.prefixes.append(path)
			else:
				if '*' in path:
					wild_files = glob.glob(f'{project_root}/{path}', recursive=True)
					self.files += [os.path.relpath(i, project_root) for i in wild_files]
				else:
					self.files += [path]

	def matches(self, path):
		apath = f'{self.abs_path}/{path}'
		project_path = os.path.relpath(apath, self.project_root)
		for prefix in self.prefixes:
			if project_path.startswith(prefix):
				return True
		return project_path in self.files


@dataclass
class Comment:
	class Mode(enum.IntFlag):
		Hash    = 0x1
		SingleC = 0x2
		MultiC  = 0x4

	exe: bool
	mode: Mode


@dataclass
class ExtInfo:
	ext: any = None
	names: list[str] = None
	cs: bool = True
	exe: bool = False
	comment: Comment = None

kHashComment = Comment(exe=False, mode=Comment.Mode.Hash)
kHashExeComment = Comment(exe=True, mode=Comment.Mode.Hash)
kCppComment = Comment(exe=False, mode=Comment.Mode.SingleC | Comment.Mode.MultiC)


def get_ext_groups():
	groups = dict(
		bison = [
			ExtInfo('y'),    # bison grammar
		],

		verilog = [
			ExtInfo('hs'),
			ExtInfo('mbif'),
			ExtInfo('scat'), # scatter load file
			ExtInfo('sdc'),  # Synopsys Design Constraint
			ExtInfo('sv'),
			ExtInfo('upf'),  # Unified Power Format
			ExtInfo('v'),
			ExtInfo('vc'),
		],

		c = [
			ExtInfo('c'),
			ExtInfo('h'),
		],

		cpp = [
			ExtInfo('hh'),
			ExtInfo('hpp'),
			ExtInfo('cc'),
			ExtInfo('cpp'),
		],

		objc = [
			ExtInfo('m'),
			ExtInfo('mm'),
		],

		misc_prog = [
			ExtInfo('s', cs=False), # .s .S - assembler
		],

		build = [
			ExtInfo('am'),
			ExtInfo('bp'), # Google blueprint
			ExtInfo('cmake', names=['CMakeLists.txt']),
			ExtInfo('m4'),
			ExtInfo('mk'),
			ExtInfo(names=[
				'Kbuild',
				'Kconfig',
				'Makefile',
				'Makefile.inc',
				'Mconfig'
			], comment=ExtInfo.CommentType.Hash),
			ExtInfo(names=['Dockerfile']),
			ExtInfo(names=['Doxyfile']),
		],

		web = [
			ExtInfo('css'),
			ExtInfo('html'),
		],

		image = [
			ExtInfo('ico'),
			ExtInfo('icns'),
			ExtInfo('png'),
			ExtInfo('pvr'),
		],

		java = [
			ExtInfo('jar'),
			ExtInfo('java'),
		],

		js = [
			ExtInfo('js'),
			ExtInfo('ts'),
		],

		qt = [
			ExtInfo('qrc'),
			ExtInfo('ui'),
		],

		config = [
			ExtInfo('cfg'),
			ExtInfo('desktop'),
			ExtInfo('json'),
			ExtInfo('md'),
			ExtInfo('plist'),
			ExtInfo('tcl'),
			ExtInfo('txt'),
			ExtInfo('yaml'),
			ExtInfo('yml'),
			ExtInfo('xml'),
			ExtInfo('xsl'),
			ExtInfo(names=['README']),
		],

		data = [
			ExtInfo('pdf'),
			ExtInfo('sqlite'),
			ExtInfo('zip'),
		],

		exe = [
			ExtInfo('lib'),
			ExtInfo('so'),
		],

		scripts = [
			ExtInfo(['bash', 'sh'], exe=True, comment=ExtInfo.CommentType.Hash),
			ExtInfo('csh', exe=True),
			ExtInfo('exe', exe=True),
			ExtInfo('pl', exe=True),
			ExtInfo('py', exe=True),
			ExtInfo('rb', exe=True),
		],
	)




def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--stat', action='store_true', help='')
	parser.add_argument('--utf', action='store_true')
	parser.add_argument('--eol', action='store_true')
	parser.add_argument('--exe', action='store_true')
	parser.add_argument('--lic', action='store_true')
	parser.add_argument('--files')
	parser.add_argument('--verbose', '-v', action='count', default=0)
	parser.add_argument('--root')
	parser.add_argument('--config')
	parser.add_argument('--exeref')
	args, extra_argv = parser.parse_known_args()

	check_broken_encodng = None

	def parse_args():
		nonlocal check_broken_encodng
		flags = []
		if args.utf: flags.append('utf')
		if args.eol: flags.append('eol')
		if args.exe: flags.append('exe')
		if args.lic: flags.append('lic')
		if not args.files is None: flags.append('files')
		if len(flags) > 1:
			dashed_flags = [f'--{f}' for f in flags]
			raise AttributeError(f'Arguments are mutually exclusive: {dashed_flags}')
		check_broken_encodng = len(flags) == 0
	parse_args()

	if len(extra_argv) == 0:
		project_path = os.curdir
	elif len(extra_argv) == 1:
		project_path = extra_argv[0]
	else:
		raise AttributeError(f'Too many paths: {extra_argv}')
	abs_path = os.path.realpath(os.path.abspath(project_path))

	if args.config is None:
		config = dict()
	else:
		with open(args.config) as f:
			config = yaml.load(f, Loader=yaml.FullLoader)
			if type(config) != dict:
				raise AttributeError(f'Config must be dict: {type(config)}')

	scan_mimes = args.stat or check_broken_encodng or args.utf or args.eol

	known_groups = dict(
		bison = dict(
			non_exe_suffixes = [
				'y',     # bison grammar
			],
		),

		verilog = dict(
			non_exe_suffixes = [
				'hs',
				'mbif',
				'scat', # scatter load file
				'sdc', # Synopsys Design Constraint
				'sv',
				'upf', # Unified Power Format
				'v',
				'vc',
			],
		),

		misc = dict(
			non_exe_suffixes = [
				'am',
				'bp', # Google blueprint
				'c',
				'cc',
				'cfg',
				'cmake',
				'cpp',
				'css',
				'desktop',
				'h',
				'hh',
				'html',
				'hpp',
				'ico',
				'icns',
				'jar',
				'java',
				'json',
				'lib',
				'm',
				'm4',
				'md',
				'mk',
				'mm',
				'pdf',
				'plist',
				'png',
				'pvr',
				's', # .s .S - assembler
				'so',
				'sqlite',
				'tcl',
				'txt',
				'ui',
				'yaml',
				'yml',
				'xml',
				'xsl',
				'zip',
			],
			non_exe_names = [
				'Dockerfile',
				'Doxyfile',
				'Kbuild',
				'Kconfig',
				'Makefile',
				'Makefile.inc',
				'Mconfig',
				'README',
			],
			exe_suffixes = [
				'bash',
				'csh',
				'exe',
				'js',
				'pl',
				'py',
				'rb',
				'sh',
			],
		),

		user = config.get('exe_group', {}),
	)

	if args.root is None:
		project_root = os.getcwd()
	else:
		project_root = os.path.realpath(os.path.abspath(args.root))

	def make_path_matcher(path):
		return PathMatcher(abs_path, project_root, path)

	def get_config_path(path):
		return os.path.relpath(f'{os.path.abspath(project_root)}/{path}', abs_path)

	if os.path.isfile(abs_path):
		folder_path = None
	else:
		folder_path = abs_path

	def cleanup_files():
		for mode in args.files.split(','):
			if mode == 'pycache':
				def scan_path(dir_path):
					file_names = sorted(os.listdir(f'{project_path}/{dir_path}'))
					for file_name in file_names:
						if dir_path == '.':
							file_path = file_name
						else:
							file_path = f'{dir_path}/{file_name}'
						full_path = f'{project_path}/{file_path}'
						st = os.stat(full_path, follow_symlinks=False)
						if stat.S_ISDIR(st.st_mode):
							if file_name == '__pycache__':
								print(f'Deleting: {file_path}')
								shutil.rmtree(full_path)
							else:
								scan_path(file_path)
				scan_path('.')
			else:
				raise AttributeError(f'Unknown --files mode: {mode}')

	if not args.files is None:
		cleanup_files()
		return

	class CollectingFilesPrinter(LinePrinter):
		def __init__(self):
			LinePrinter.__init__(self)

		def printer(self):
			nonlocal files
			if files is not None:
				suffix = str(len(files))
			else:
				suffix = '...'
			print(f'Collecting files: {suffix}', end='')

	files = None

	collecting_files_printer = CollectingFilesPrinter()
	collecting_files_printer.print()

	if folder_path is None:
		files = [abs_path]
	else:
		files = utils.find_unique_paths(folder_path)

	collecting_files_printer.print(True)

	stat_file_list = []
	stat_text_list = []
	stat_rest_list = []

	count_for_mime_type = dict()

	need_line_break = False

	def maybe_line_break():
		nonlocal need_line_break
		if need_line_break:
			print()
			need_line_break = False

	class PercentagePrinter(LinePrinter):
		def __init__(self, prefix, total, step):
			LinePrinter.__init__(self)

			self.prefix = prefix
			self.index = 0
			self.total = total
			self.step = step
			self.total_len = len(str(self.total))

		def inc(self):
			self.index += 1
			if (self.index % self.step) == 0:
				self.print()

		def printer(self):
			if self.index == self.total:
				suffix = self.final_message()
			else:
				perc = self.index * 100 / self.total
				perc_str = f'{perc : .2f}'
				suffix = f'{self.index : >{self.total_len}} / {self.total}    {perc_str : >6}%'
			print(f'{self.prefix}: {suffix}', end='')

	def is_text(mime_type, charset):
		if charset == 'binary':
			return False
		if mime_type.startswith('text/'):
			return True
		if mime_type == 'application/json':
			return True
		return False

	def scan_files():
		nonlocal need_line_break

		ignore_matcher = make_path_matcher(config.get('ignore'))

		class ScanFilesPrinter(PercentagePrinter):
			def __init__(self):
				PercentagePrinter.__init__(self, 'Scanning file types', len(files), 10)

			def final_message(self):
				nonlocal stat_text_list
				return f'{len(stat_text_list)} text files'

		scan_files_printer = ScanFilesPrinter()
		scan_files_printer.print()

		for file in files:
			scan_files_printer.inc()

			local_path = file

			if folder_path is None:
				full_path = file
			else:
				full_path = f'{folder_path}/{file}'

			st_mode = os.stat(full_path).st_mode
			stat_file_list.append(FileInfo(local_path, None, None, st_mode))

			if scan_mimes:
				mime_output = subprocess.run(['file', '--mime', '-b', full_path], check=True, universal_newlines=True, stdout=subprocess.PIPE).stdout.strip()
				mime_type, charset_info = mime_output.split('; ', maxsplit=1)
				charset_key, charset_value = charset_info.split('=', maxsplit=1)
				mime_type_count = count_for_mime_type.get(mime_type)
				if mime_type_count is None:
					mime_type_count = 1
				else:
					mime_type_count += 1
				count_for_mime_type[mime_type] = mime_type_count
				is_ignored = ignore_matcher.matches(local_path)
				if not is_ignored and is_text(mime_type, charset_value):
					stat_list = stat_text_list
				else:
					stat_list = stat_rest_list
				stat_list.append(FileInfo(local_path, mime_type, charset_value, None))

		scan_files_printer.print(True)

		print(f'    File count: {len(stat_file_list)}')
		if scan_mimes:
			print(f'        text : {len(stat_text_list)}')
			print(f'        rest : {len(stat_rest_list)}')

		if args.stat or args.verbose:
			sorted_mime_types = sorted(list(count_for_mime_type.keys()))
			print()
			print(f'    Mime types: {len(sorted_mime_types)}')
			longest_mime_type = 0
			for mime_type in sorted_mime_types:
				longest_mime_type = max(longest_mime_type, len(mime_type))
			for mime_type in sorted_mime_types:
				print(f'        {mime_type : <{longest_mime_type}} : {count_for_mime_type[mime_type]}')
			need_line_break = True

	scan_files()

	non_utf_list = None
	fixed_list = []
	unfixed_list = []

	def get_file_path(file_info):
		if folder_path is None:
			return file_info.path
		else:
			return f'{folder_path}/{file_info.path}'

#	def make_utf8(file_info):
#		file_path = get_file_path(file_info)
#		with open(file_path, 'rb') as f:
#			old_md5_sum = hashlib.md5(f.read()).digest()

#		lines = []
#		with open(file_path, 'r', newline='') as f:
#			for line in f:
#				lines.append(line)
#		str_data = ''.join(lines)
#		with open(file_path, 'w') as f:
#			f.write(str_data)

#		with open(file_path, 'rb') as f:
#			new_md5_sum = hashlib.md5(f.read()).digest()

#		same = old_md5_sum == new_md5_sum

#		if not same:
#			fixed_list.append(file_info)
#		else:
#			unfixed_list.append(file_info)

	def check_utf8(file_info):
		file_path = get_file_path(file_info)
		with open(file_path, 'rb') as f:
			old_md5_sum = hashlib.md5(f.read()).digest()

		lines = []
		with open(file_path, 'r', newline='') as f:
			for line in f:
				lines.append(line)
		str_data = ''.join(lines)

		new_md5_sum = hashlib.md5(str_data.encode('utf-8')).digest()
		if new_md5_sum != old_md5_sum:
			raise RuntimeError('')

	def fix_eol(file_info):
		def fix_line(line):
			while len(line):
				last_char = line[-1:]
				# space - tab - LF - CR - vertical tab
				# but ignore Form Feed \x0c
				if not last_char in ' \t\n\r\x0b':
					break
				line = line[:-1]
			line += '\n'
			return line

		file_path = get_file_path(file_info)
		with open(file_path, 'rb') as f:
			old_md5 = hashlib.md5(f.read())

		with open(file_path, 'r', newline='') as f:
			lines = []
			line = None
			for line in f:
				if line[-1:] == '\n':
					line_fixed = True
					line = fix_line(line)
				else:
					# if line is not terminated with \n then it might be other
					# line break character, which source code wants to preserve, so
					# keep such a line as is
					line_fixed = False
				lines.append(line)

			# if last line is unfixed that means file is not terminated with a
			# line break, thus force fix the last line
			if not line is None and not line_fixed:
				last_line = lines[-1:][0]
				lines = lines[:-1]
				lines.append(fix_line(last_line))

		with open(file_path, 'w') as f:
			f.write(''.join(lines))

		with open(file_path, 'rb') as f:
			new_md5 = hashlib.md5(f.read())

		same = old_md5.digest() == new_md5.digest()
		if not same:
			fixed_list.append(file_info)
		else:
			unfixed_list.append(file_info)

	def print_broken(broken_list):
		if not broken_list:
			return

		print()
		print('ERROR: Found broken UTF-8 files with corrupted/mixed encoding.')
		print('       Fix files below manually and try again.')

		for file_info, e in broken_list:
			print()
			print(f'    {file_info.path}')
			print(f'        charset : {file_info.charset}')
			print(f'        error   : {e}')

	def find_non_utf():
		nonlocal non_utf_list

		maybe_line_break()

		non_utf_list = []

		class AutoUtfPrinter(PercentagePrinter):
			def __init__(self):
				PercentagePrinter.__init__(self, 'Detecting non UTF-8', len(stat_text_list), 10)

			def final_message(self):
				return f'{len(non_utf_list)}'

		utf_printer = AutoUtfPrinter()
		utf_printer.print()

		for file_info in stat_text_list:
			utf_printer.inc()

			try:
				check_utf8(file_info)
			except UnicodeDecodeError as e:
				non_utf_list.append((file_info, e))

		utf_printer.print(True)

	def check_broken_utf():
		nonlocal non_utf_list

		if non_utf_list:
			broken_list = []

			maybe_line_break()

			class IconvCheckUtfPrinter(PercentagePrinter):
				def __init__(self):
					PercentagePrinter.__init__(self, 'Checking broken UTF-8 files', len(non_utf_list), 10)

				def final_message(self):
					return f'{len(broken_list)}'

			utf_printer = IconvCheckUtfPrinter()
			utf_printer.print()

			for file_info, le in non_utf_list:
				utf_printer.inc()

				file_path = get_file_path(file_info)

				try:
					with tempfile.NamedTemporaryFile() as tf:
						subprocess.run(['iconv', '-f', file_info.charset, '-t', 'utf-8', file_path, '-o', tf.name], stderr=subprocess.DEVNULL, check=True)
				except subprocess.CalledProcessError:
					broken_list.append((file_info, le))

			utf_printer.print(True)

			if broken_list:
				print_broken(broken_list)
				sys.exit(1)

		print('No broken encoding found in text files')

	def cleanup_utf():
		maybe_line_break()

		class IconvFixUtfPrinter(PercentagePrinter):
			def __init__(self):
				PercentagePrinter.__init__(self, 'Converting files into UTF-8', len(non_utf_list), 10)

			def final_message(self):
				return f'{len(non_utf_list)}'

		utf_printer = IconvFixUtfPrinter()
		utf_printer.print()

		for file_info, le in non_utf_list:
			utf_printer.inc()

			file_path = get_file_path(file_info)

			tmp_file_path = f'{file_path}.tmp.cleanup'
			subprocess.run(['iconv', '-f', file_info.charset, '-t', 'utf-8', file_path, '-o', tmp_file_path], stderr=subprocess.DEVNULL, check=True)
			os.rename(tmp_file_path, file_path)

		utf_printer.print(True)

	def cleanup_eol():
		nonlocal fixed_list, unfixed_list

		broken_list = []

		class EolPrinter(PercentagePrinter):
			def __init__(self):
				PercentagePrinter.__init__(self, 'Fixing EOL and trailing whitespace', len(stat_text_list), 10)

			def final_message(self):
				return 'DONE'

		eol_printer = EolPrinter()
		eol_printer.print()

		fixed_list = []

		for file_info in stat_text_list:
			eol_printer.inc()

			try:
				fix_eol(file_info)
			except UnicodeDecodeError as e:
				broken_list.append((file_info, e))

		eol_printer.print(True)

		print(f'    Already OK : {len(unfixed_list)}')
		print(f'    Fixed      : {len(fixed_list)}')

		if broken_list:
			print(f'    Broken     : {len(broken_list)}')
			print_broken(broken_list)
			sys.exit(1)

	def cleanup_exe():
		nonlocal config

		def make_group_list(name):
			group_list = []
			for group_name, item in known_groups.items():
				group_list += item.get(name, [])
			return group_list

		known_non_exe_suffixes = make_group_list('non_exe_suffixes')
		known_non_exe_names = make_group_list('non_exe_names')
		known_exe_suffixes = make_group_list('exe_suffixes')

		exe_matcher = make_path_matcher(config.get('exe'))
		nonexe_matcher = make_path_matcher(config.get('nonexe'))

		class ExePrinter(PercentagePrinter):
			def __init__(self):
				PercentagePrinter.__init__(self, "Fixing exe permissions", len(stat_file_list), 10)

			def final_message(self):
				return 'DONE'

		exe_printer = ExePrinter()
		exe_printer.print()

		exe_list = []

		exe_perms = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

		for file_info in stat_file_list:
			exe_printer.inc()

			has_exe = (exe_perms & file_info.st_mode) != 0

			if has_exe:
				exe_list.append(file_info)

		exe_printer.print(True)

		print(f'Exe files: {len(exe_list)}')

		nonexe_files = []
		known_non_exe_files = []
		unknown_ext_files = []
		no_ext_files = []

		for file_info in exe_list:
			if not args.exeref is None:
				ref_path = f'{args.exeref}/{file_info.path}'
				if os.path.isfile(ref_path):
					s = os.stat(ref_path)
					has_exe = (exe_perms & s.st_mode) != 0
					if not has_exe:
						nonexe_files.append(file_info)
				continue

			if exe_matcher.matches(file_info.path):
				continue

			if nonexe_matcher.matches(file_info.path):
				nonexe_files.append(file_info)
				continue

			file_name = os.path.basename(file_info.path)
			ext = os.path.splitext(file_name)[1]

			if ext == '.in':
				# input file, resolve second extension
				file_name = file_name[:-3]
				ext = os.path.splitext(file_name)[1]

			if file_name in known_non_exe_names:
				known_non_exe_files.append(file_info)
			else:
				if ext:
					if ext[0] != '.':
						raise AttributeError(f'Invalid ext: {file_info.path}')
					ext = ext[1:].lower()
					if ext in known_exe_suffixes:
						pass
					elif ext in known_non_exe_suffixes:
						known_non_exe_files.append(file_info)
					else:
						unknown_ext_files.append(file_info)
				else:
					no_ext_files.append(file_info)

		def fix_exe(file_infos):
			for file_info in file_infos:
				file_path = get_file_path(file_info)
				new_perms = file_info.st_mode & ~exe_perms
				os.chmod(file_path, new_perms)

		if nonexe_files:
			print(f'    Fixed preconfigured non exe files: {len(nonexe_files)}')
			if args.verbose:
				for file_info in nonexe_files:
					print(f'        {file_info.path}')

		if known_non_exe_files:
			print(f'    Fixed known non exe extension files: {len(known_non_exe_files)}')
			if args.verbose:
				for file_info in known_non_exe_files:
					print(f'        {file_info.path}')

		if unknown_ext_files or no_ext_files:
			print()
			print('ERROR: Some files have executable flag, but it is unclear how to treat those.')
			print('       Adjust config and repeat.')
			print()

			if unknown_ext_files:
				print(f'    Unknown extension files: {len(unknown_ext_files)}')
				for file_info in unknown_ext_files:
					print(f'        {file_info.path}')

			if no_ext_files:
				print(f'    No extension files: {len(no_ext_files)}')
				for file_info in no_ext_files:
					print(f'        {file_info.path}')

			sys.exit(1)

		fix_exe(nonexe_files)
		fix_exe(known_non_exe_files)

	if check_broken_encodng or args.utf:
		find_non_utf()

	if check_broken_encodng:
		check_broken_utf()

	if args.utf:
		cleanup_utf()

	if args.eol:
		cleanup_eol()

	if args.exe:
		cleanup_exe()


if __name__ == '__main__':
	main()
