import os
import json
from universal.files import char_replace

def write_creature(jsondir, struct, source):
	print("%s (%s): %s" %(struct['game-obj'], source, struct['name']))
	filename = create_creature_filename(jsondir, struct)
	fp = open(filename, 'w')
	json.dump(struct, fp, indent=4)
	fp.close()

def create_creature_filename(jsondir, struct):
	title = jsondir + "/" + char_replace(struct['name']) + ".json"
	return os.path.abspath(title)
