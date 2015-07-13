
import sys
import math
import argparse

import numpy as np
import networkx as nx

import resistances
from circuit import save_circuit
from util import zip_dict

# (these top two should be flipped x/y)
# Column numbers: (zigzag dimension)
#
#     0  0        0  0      cell row
#  1        1  1        1       0
#     2  2        2  2          1
#  3        3  3        3       2
#     4  4        4  4          3
# (5)       5  5       (5)
#
# Row numbers: (armchair direction)
#
#     0  1        2  3
#  0        1  2        3
#     0  1        2  3
#  0        1  2        3
#     0  1        2  3
#           1  2
#
# If you were to plot these indices and the bonds between, you'd get a brick-like layout:
#
#  *-*-*-*-*-*-*
#  |   |   |   |
#  *-*-*-*-*-*-*-*
#    |   |   |   |
#  *-*-*-*-*-*-*-*
#  |   |   |   |
#  *-*-*-*-*-*-*
#

# FIXME: this whole file is a mess

def main(argv):
	parser = argparse.ArgumentParser()
	parser.add_argument('rows', metavar='LENGTH', type=int)
	parser.add_argument('cols', metavar='WIDTH', type=int)
	parser.add_argument('--output', '-o', type=str, required=True, help='.gpickle output file')

	args = parser.parse_args(argv[1:])

	values = make_circuit(args.rows, args.cols)
	save_output(args.output, *values)


def make_circuit(cellrows, cellcols):
	nrows,ncols = hex_grid_dims(cellrows,cellcols)

	# Grid nodes
	gridvs = [[grid_label(row,col) for col in range(ncols)] for row in range(nrows)]

	gridxs, gridys = hex_grid_xy_arrays(cellrows,cellcols)
	xs = {v: x for v,x in zip(flat_iter(gridvs), gridxs.flat)}
	ys = {v: y for v,y in zip(flat_iter(gridvs), gridys.flat)}

	# Connector nodes
	topv = 'top'
	xs[topv] = -2.0
	ys[topv] = max(gridys.flat) + 1.0

	botv = 'bot'
	xs[botv] = -2.0
	ys[botv] = -1.0

	# Circuit object
	g = hex_bridge_grid_circuit(gridvs)

	g.add_nodes_from([topv, botv])

	# Link top/bot with battery
	add_battery(g, botv, topv, 1.0)

	#----------------
	# connect top/bot to nodes in graph
	# due to zigzag pattern this is not entirely straightforward

	# first column for "true" top/bottom rows
	botstart = 1
	topstart = (nrows+1) % 2

	# doublecheck
	assert gridys[0][botstart]  < gridys[0][1-botstart]
	assert gridys[-1][topstart] > gridys[-1][1-topstart]

	for v in gridvs[0][botstart::2]:
		add_wire(g,v,botv)

	for v in gridvs[-1][topstart::2]:
		add_wire(g,v,topv)

	deletable = {v: True for v in g}
	deletable[topv] = False
	deletable[botv] = False

	measure_edge = (botv, topv)

	return g, xs, ys, deletable, measure_edge

def save_output(path, g, xs, ys, deletable, measure_edge):

	#TODO may no longer be worthwhile now that we call out to functions which
	#  ought to do validation for us (however I don't think it actually does currently!)
	assert validate_graph_attributes(g)

	save_circuit(g, path)

	basename = drop_extension(path)

	# remove e.g. numpy type information from floats
	xs = {v:float(x) for v,x in xs.items()}
	ys = {v:float(x) for v,x in ys.items()}

	pos = zip_dict(xs, ys)
	save_gpos(pos, basename + '.planar.gpos')

	config = resistances.Config()
	config.set_measured_edge(*measure_edge)
	config.set_no_defect([])
	config.save(basename + '.defect.toml')

# Total number of rows/cols of vertices
def hex_grid_dims(cellrows, cellcols):
	return (
		cellrows + 1,
		2*cellcols + 1,
	)

def hex_grid_xy_arrays(cellrows, cellcols):
	nrows,ncols = hex_grid_dims(cellrows, cellcols)

	# 2d arrays containing row or column of each node
	rows = np.outer(range(nrows), [1]*ncols)
	cols = np.outer([1]*nrows, range(ncols))

	xs = 0.5 * math.sqrt(3) * cols

	ys = 1.5 * rows # baseline height
	ys += 0.5 * ((rows + cols + 1) % 2)  # zigzag across row

	return xs, ys

def grid_label(row,col):
	return 'grid@{},{}'.format(row,col)

# a flattened iterator over a (singly-)nested iterable.
def flat_iter(lst):
	for item in lst:
		yield from item

def hex_bridge_grid_circuit(gridvs):
	g = nx.Graph()

	g.add_nodes_from(flat_iter(gridvs))

	nrows,ncols = np.shape(gridvs)

	# horizontal edges
	for row in range(nrows):
		# all the way across
		for col in range(ncols-1):
			add_resistor(g, gridvs[row][col], gridvs[row][col+1], 1.0)

	# vertical edges
	for row in range(nrows-1):
		# take every other column (alternating between rows)
		for col in range(row % 2, ncols, 2):
			add_resistor(g, gridvs[row+1][col], gridvs[row][col], 1.0)

	return g

# FIXME HACK
# Should use CircuitBuilder and save_circuit instead
from circuit import EATTR_RESISTANCE, EATTR_VOLTAGE, EATTR_SOURCE

def add_wire(g, s, t):
	g.add_edge(s, t)
	g.edge[s][t][EATTR_RESISTANCE] = 0.0
	g.edge[s][t][EATTR_VOLTAGE]    = 0.0
	g.edge[s][t][EATTR_SOURCE]     = s

def add_resistor(g, s, t, resistance):
	add_wire(g,s,t)
	g.edge[s][t][EATTR_RESISTANCE] = resistance

def add_battery(g, s, t, voltage):
	add_wire(g,s,t)
	g.edge[s][t][EATTR_VOLTAGE] = voltage

# Verifies that any node/edge attributes in g are completely defined for all nodes/edges.
# Raises an error or returns True (for use in assertions)
def validate_graph_attributes(g):
	all_node_attributes = set()
	for v in g:
		all_node_attributes.update(g.node[v])

	for attr in all_node_attributes:
		if len(nx.get_node_attributes(g, attr)) != g.number_of_nodes():
			raise AssertionError('node attribute {} is set on some nodes but not others'.format(repr(attr)))

	all_edge_attributes = set()
	for s,t in g.edges():
		all_edge_attributes.update(g.edge[s][t])

	for attr in all_edge_attributes:
		if len(nx.get_edge_attributes(g, attr)) != g.number_of_edges():
			raise AssertionError('edge attribute {} is set on some edges but not others'.format(repr(attr)))

	return True

# FIXME should be in some io module (note: reading function is currently in cyclebasis_provider)
def save_gpos(pos, path):
	# TODO should do validation once moved
	import json
	d = {
		'labels':    list(pos.keys()),
		'positions': [list(map(float, p)) for p in pos.values()],
	}
	s = json.dumps(d)
	with open(path, 'w') as f:
		f.write(s)

def drop_extension(path):
	import os
	head,tail = os.path.split(path)
	if '.' in tail:
		tail, _ = tail.rsplit('.', 1)
	return os.path.join(head, tail)

if __name__ == '__main__':
	main(list(sys.argv))
