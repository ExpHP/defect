#!/usr/bin/env python3

import sys
import math
import json
import argparse
import itertools

import numpy as np
import networkx as nx

import defect.graph.path as vpath
from defect.buildcb import build_cyclebasis_terminal

import defect.trial
import defect.filetypes.internal as fileio
from defect.circuit import save_circuit

def main(prog, argv):
	parser = argparse.ArgumentParser(prog=prog)
	parser.add_argument('rows', metavar='LENGTH', type=int)
	parser.add_argument('cols', metavar='WIDTH', type=int)
	parser.add_argument('--verbose', '-v', action='store_true')
	parser.add_argument('--output-cb', '-C', metavar='PATH', type=str, help='generate .cyclebasis file')
	parser.add_argument('--output', '-o', type=str, required=True, help='.gpickle output file')

	args = parser.parse_args(argv)

	cellrows, cellcols = args.rows, args.cols

	if args.verbose:
		print('Generating graph and attributes')
	g = make_circuit(cellrows, cellcols)
	xys = full_xy_dict(cellrows, cellcols)
	measured_edge = battery_vertices()

	if args.verbose:
		print('Saving circuit')
	save_output(args.output, g, xys, measured_edge)

	if args.output_cb is not None:
		if args.verbose:
			print('Collecting desirable cycles')
		good = collect_good_cycles(g, cellrows, cellcols)

		assert validate_paths(g, good)

		if args.verbose:
			print('Generating fallback cycles')
		fallback = nx.cycle_basis(g)

		cyclebasis = build_cyclebasis_terminal(good, fallback, thorough=False, verbose=args.verbose)
		fileio.cycles.write_cycles(cyclebasis, args.output_cb)

def make_circuit(cellrows, cellcols):
	g = nx.Graph()

	add_hex_grid_edges(g, cellrows, cellcols)
	add_connector_edges(g, cellrows, cellcols)

	# The measured edge:
	bot, top = battery_vertices()
	add_battery(g, bot, top, 1.0)

	return g

def save_output(path, g, xys, measure_edge):
	save_circuit(g, path)

	basename = drop_extension(path)

	# remove e.g. numpy type information from floats
	xys = {v:tuple(map(float, xy)) for v,xy in xys.items()}
	# note we do not produce '.planar.gpos' because this is not planar!
	fileio.gpos.write_gpos(xys, basename + '.display.gpos')

	config = defect.trial.Config()
	config.set_measured_edge(*measure_edge)
	config.set_no_defect([])
	config.save(basename + '.defect.toml')

#-----------------------------------------------------------

# produces a list of short, desirable cycles (not necessarily linearly independent)
#  which may serve as the foundation for a complete cyclebasis (via build_cyclebasis)
def collect_good_cycles(g, cellrows, cellcols):
	result = []

	for cellrow,cellcol in all_cells(cellrows,cellcols):
		positions = cell_positions_ccw(cellrow,cellcol)

		# lists of vertices at each point in the hexagon
		vertex_groups = [hex_vertices(i,j) for (i,j) in positions]

		# grid cycle composed entirely of one layer (a hexagon)
		cycle = list(map(lambda x:x[0], vertex_groups))
		cycle.append(cycle[0]) # make cyclic
		result.append(cycle)

		# a cycle can be formed by each pair of S atoms and their neighboring Mo atoms.
		# There are 3 such cycles in each cell, though one can usually be expressed
		#  as a linear combination of cycles from other cells.
		it = range(len(positions))
		it = filter(lambda i: not hex_is_Mo(*positions[i]), it)
		for i in it:
			# vertex_groups[i-1] to [i+1] (inclusive) contains the 4 vertices
			Mo1,   = vertex_groups[i-1]
			S1, S2 = vertex_groups[i]
			Mo2,   = vertex_groups[(i+1)%len(vertex_groups)]
			result.append([Mo1, S1, Mo2, S2, Mo1])

	# a bunch of length 4 cycles between battery vertices and the edge vertices
	for batv in battery_vertices():
		result.extend(cycles_upto(g, batv, 4))

	return result

def validate_paths(g, paths):
	for path in paths:
		for v in path:
			if v not in g:
				raise AssertionError('graph does not contain vertex {}! (Path: {})'.format(repr(v),path))

		for s,t in vpath.edges(path):
			if not g.has_edge(s,t):
				raise AssertionError('graph does not contain edge ({},{})! (Path: {})'.format(repr(s),repr(t),path))
	return True

#-----------------------------------------------------------
# Methods for adding edges to the graph

def add_hex_grid_edges(g, cellrows, cellcols):
	nrows,ncols = hex_grid_dims(cellrows, cellcols)

	# horizontal edges - all the way across
	for row, col in itertools.product(range(nrows), range(ncols-1)):
		v1s = hex_vertices(row, col)
		v2s = hex_vertices(row, col+1)
		for v1, v2 in itertools.product(v1s, v2s):
			add_resistor(g, v1, v2, 1.0)

	# vertical edges - only between vertices close to eachother vertically
	for row, col in itertools.product(range(nrows-1), range(ncols)):
		if hex_is_upper(row, col):
			v1s = hex_vertices(row, col)
			v2s = hex_vertices(row+1, col)
			for v1, v2 in itertools.product(v1s, v2s):
				add_resistor(g, v1, v2, 1.0)

# links the hex grid to the battery vertices
def add_connector_edges(g, cellrows, cellcols):
	nrows,ncols = hex_grid_dims(cellrows, cellcols)

	bot, top = battery_vertices()

	for col in range(ncols):
		if not hex_is_upper(0, col):
			for v in hex_vertices(0, col):
				add_wire(g, bot, v)

		if hex_is_upper(nrows-1, col):
			for v in hex_vertices(nrows-1, col):
				add_wire(g, top, v)

# FIXME HACK
# Should use CircuitBuilder and save_circuit instead
from defect.circuit import EATTR_RESISTANCE, EATTR_VOLTAGE, EATTR_SOURCE

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

#-----------------------------------------------------------
# Top level methods for building attribute dicts

# x,y tuples (for visualization purposes only)
def full_xy_dict(cellrows, cellcols):
	d = {}
	d.update(hex_grid_xy_dict(cellrows,cellcols))
	d.update(battery_xy_dict(cellrows,cellcols))
	return d

#-----------------------------------------------------------
# Methods dealing with the hexagonal bridge as a whole

# Total number of rows/cols of vertices
def hex_grid_dims(cellrows, cellcols):
	return (
		cellrows + 1,
		2*cellcols + 1,
	)

# returns ([minx, miny], [maxx, maxy]) of points in grid
def hex_grid_rectangle_points(cellrows, cellcols):
	xys = np.vstack(hex_xy(i,j) for (i,j) in hex_grid_positions(cellrows,cellcols))
	return xys.min(axis=0), xys.max(axis=0)

# (row,col) tuples, which are accepted by most functions dealing with individual grid vertices
def hex_grid_positions(cellrows, cellcols):
	nrows,ncols = hex_grid_dims(cellrows, cellcols)
	return list(itertools.product(range(nrows),range(ncols)))

def hex_grid_Mo_positions(cellrows, cellcols):
	return [pos for pos in hex_grid_positions(cellrows,cellcols) if hex_is_Mo(*pos)]

def hex_grid_S_positions(cellrows, cellcols):
	return [pos for pos in hex_grid_positions(cellrows,cellcols) if not hex_is_Mo(*pos)]

# vertices (i.e. node labels for the graph)
def hex_grid_vertices(cellrows, cellcols):
	result = []
	result.extend(hex_grid_Mo_vertices(cellrows, cellcols))
	for layer in S_LAYERS:
		result.extend(hex_grid_S_vertices(cellrows, cellcols, layer))
	return result

def hex_grid_Mo_vertices(cellrows, cellcols):
	return [hex_Mo_vertex(i,j) for (i,j) in hex_grid_Mo_positions(cellrows,cellcols)]

def hex_grid_S_vertices(cellrows, cellcols, layer):
	assert layer in S_LAYERS
	return [hex_S_vertex(i,j,layer) for (i,j) in hex_grid_S_positions(cellrows,cellcols)]

# x,y tuples (for visualization purposes only)
def hex_grid_xy_dict(cellrows, cellcols):
	d = {}
	d.update({hex_Mo_vertex(i,j):hex_xy(i,j) for (i,j) in hex_grid_Mo_positions(cellrows,cellcols)})
	for layer in S_LAYERS:
		d.update({hex_S_vertex(i,j,layer):hex_xy(i,j) for (i,j) in hex_grid_S_positions(cellrows,cellcols)})

	# offset the layers slightly to aid in visualization
	displacement = np.array([0.15, 0.0])
	for (i,j) in hex_grid_S_positions(cellrows,cellcols):
		d[hex_S_vertex(i,j,1)] -= displacement
		d[hex_S_vertex(i,j,2)] += displacement

	return d

#-----------------------------------------------------------
# Methods for dealing with a point on the hex bridge

S_LAYERS = (1,2) # legal specifiers for the layer of a sulfur atom

def hex_Mo_vertex(row, col):
	assert row>=0 and col>=0
	assert hex_is_Mo(row, col)
	return "Mo@{},{}".format(row,col)

def hex_S_vertex(row, col, layer):
	assert row>=0 and col>=0
	assert not hex_is_Mo(row,col)
	assert layer in S_LAYERS
	return "S{}@{},{}".format(layer,row,col)

# all vertices at a given point
def hex_vertices(row, col):
	assert row>=0 and col>=0
	if hex_is_Mo(row, col):
		return [hex_Mo_vertex(row,col)]
	else:
		return [hex_S_vertex(row,col,layer) for layer in S_LAYERS]

def hex_is_Mo(row, col):
	assert row>=0 and col>=0
	return not hex_is_upper(row,col)

# Each row is a zigzag; this marks the "raised" vertices of each row
def hex_is_upper(row, col):
	assert row>=0 and col>=0
	return (row+col) % 2 == 0

# xy for visualization purposes
def hex_xy(row, col):
	assert row>=0 and col>=0
	zigzag_offset = 0.5 if hex_is_upper(row,col) else 0.0
	return np.array([
		0.5 * math.sqrt(3) * col,
		1.5 * row + zigzag_offset,
	])

#-----------------------------------------------------------
# methods for working with cells of the bridge


def all_cells(cellrows, cellcols):
	it = itertools.product(range(cellrows), range(cellcols))

	# every other row has (cellcols-1) cols
	it = filter(lambda rc: not (rc[0]%2==1 and rc[1] == cellcols-1), it)
	return it

# Identifies the 6 positions belonging to a hexagonal cell in ccw order
def cell_positions_ccw(cellrow, cellcol):
	brow,bcol = cell_bottom_position(cellrow,cellcol)
	return [
		(brow,   bcol),
		(brow,   bcol+1),
		(brow+1, bcol+1),
		(brow+1, bcol),
		(brow+1, bcol-1),
		(brow,   bcol-1),
	]

# the bottom point of the hexagonal cell
def cell_bottom_position(cellrow, cellcol):
	return (
		cellrow,
		2*cellcol + 1 + cellrow%2,
	)

#-----------------------------------------------------------
# special vertices inserted to provide an edge whose current is measured

# vertices (i.e. node labels for the graph)
def battery_vertices():
	return "bot", "top"

# x,y tuples (for visualization purposes only)
def battery_xy_dict(cellrows, cellcols):
	(xmin,ymin),(xmax,ymax) = hex_grid_rectangle_points(cellrows, cellcols)
	bot,top = battery_vertices()

	# positions chosen to reduce overlapping visuals
	return {
		bot: (xmin - 2.0, ymin - 1.0 - 0.1 * cellrows),
		top: (xmin - 2.0, ymax + 1.0 + 0.1 * cellrows),
	}

#-----------------------------------------------------------
# Collect cycles up to n edges long starting at v.
def cycles_upto(g, v, n):
	cycles = []
	for nbr in g.neighbors(v):
		cycles.extend(cycles_upto_impl(g, n-1, (v,nbr)))

	# filter out duplicate cycles in opposite directions
	filtered = set()
	for x in cycles:
		if x[:-1] not in filtered:
			filtered.add(x)

	return filtered

def cycles_upto_impl(g, n, path):
	assert len(path) >= 2

	if path[-1] == path[0]:
		yield path
		return

	if n == 0:
		return

	for nbr in g.neighbors(path[-1]):
		if (nbr != path[-2]) and (nbr not in path[1:]):
			yield from cycles_upto_impl(g, n-1, path + (nbr,))

#-----------------------------------------------------------

def drop_extension(path):
	import os
	head,tail = os.path.split(path)
	if '.' in tail:
		tail, _ = tail.rsplit('.', 1)
	return os.path.join(head, tail)

if __name__ == '__main__':
	prog, *argv = sys.argv
	main(prog, argv)
