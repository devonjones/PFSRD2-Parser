import os
import glob

def char_replace(instr):
	for char in ['(', ')', '[', ']', ',', '/', "'", ":", ";", "&"]:
		instr = instr.replace(char, '')
	instr = instr.strip()
	instr = instr.replace(' ', '_')
	return instr.lower()

def makedirs(output, game_obj, source):
	game_obj_dir = os.path.abspath(output + "/" + char_replace(game_obj) + "/" + char_replace(source))
	if not os.path.exists(game_obj_dir):
		os.makedirs(game_obj_dir)
	return game_obj_dir

#def locate_other_dbs(filename, sep):
#	parts = filename.split(sep)
#	parts.pop()
#	search = sep.join(parts) + "*.db"
#	files = glob.glob(search)
#	files.remove(filename)
#	return files

