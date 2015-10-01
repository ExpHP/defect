
import os, sys
import unittest

from defect.trial import TrialRunner, Config, node_selection, node_deletion
import defect.graph.cyclebasis

# Tests of the trial runner, to detect when a modification unintentionally
# changes the results.
#
# These take a couple of input files:
#
#  *  *.circuit and other associated input files
#  *  *.order  -- Precise list of lists of nodes to delete each step,
#                 as a JSON list.
#  *  *.output -- Expected currents for each step, as a JSON list.
#
# The actual tests (including parameters like deletion mode) are defined in
# this module.  Tests may mix and match various files of the above types.
#
# Scripts exist in the trial_runner directory for creating some of these
#  inputs.
#
#  * make_cicuits - Remakes each of the .circuit inputs (or at least, can be
#                   looked at to see what flags were used to generate them).
#                   Use this to mass-regenerate inputs when the input file
#                    format changes.
#
#  * extract_order - Takes a results.json file and produces a .order file from
#                    the order that nodes were removed in the trial.
#
# New .output files are generated with a '.new' extension each time tests are
# run.  This can be used to "bootstrap" a brand new test by running it once
# with no output, then removing the '.new' extension from the generated file.
#
# Similarly, if a change in output is deliberate, you may replace the existing
# '.output' file with the '.output.new' generated by the failed test (but please
# compare the files first to ensure that the change is as one would expect!)
#
#######################
#
#  Procedure for adding a new test:
#
#  - get a .circuit:
#     Use an existing one or generate a new one.
#     If you need a new circuit, add something to ``make_circuits`` and rerun it.
#
#  - get a .order:
#     Use an existing one or generate a new one.
#     For most tests, all you need is a .order file that selects all of the nodes
#      from the graph in a random order.  To obtain one like this, run
#      ``defect-trial`` on the graph with any settings that will run to completion
#      (e.g. multiply mode under default settings, or remove mode with --alltheway)
#      and use ``extract_order`` on the resulting json file.
#
#  - write the test:
#     Add a test to ``TrialTests``.
#     Please specify a UNIQUE name for the '.output' file.
#     Aside from that, just set the appropriate settings on the runner for
#      whatever you want to test.
#
#  - get a .output:
#     RUN the test (i.e. ``nosetests3`` in the repo root).
#     It will fail due to the '.output' file not existing.
#     However, it will also generate a '.output.new' file with the results it got
#      using your settings on the trial runner.
#     Look over the generated file, compare it against results from similar tests,
#      etc.  If everything looks good, remove the '.new' extension.
#
#######################

MY_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(MY_DIR, 'trial_tests')

def RESOURCE(fname):
	return os.path.join(TEST_DIR, fname)

class TrialTests(unittest.TestCase):

	def setUp(self):
		self.runner = TrialRunner()
		self.test_has_run = False

	# automatically called at test end
	# use this opportunity to confirm that we ran the test
	def tearDown(self):
		# only perform this check on test "success"
		if not self._test_has_failed():
			self.assertTrue(self.test_has_run, 'test was not run!')

	def _test_has_failed(self):
		# Terrible hack to determine if the test was a failure.
		# Specific to Python 3.4+
		for method, error in self._outcome.errors:
			if error:
				return True
		return False

	# Read .circuit and config files
	# This needs to reproduce some of the logic in ``defect.trial.runner.main``
	#  because there is currently no general way to do this
	def set_input(self, basename, cbfilename):
		from defect.circuit import load_circuit

		g = load_circuit(RESOURCE(basename + '.circuit'))
		config = Config.from_file(RESOURCE(basename + '.defect.toml'))

		cbfilename = RESOURCE(cbfilename)

		# Detect how to load cyclebasis by extension
		if cbfilename.endswith('.planar.gpos'):
			cycles = defect.graph.cyclebasis.planar.from_gpos(g, cbfilename)
		elif cbfilename.endswith('.cycles'):
			cycles = defect.graph.cyclebasis.from_file(cbfilename)
		else: assert False, 'test cannot load cyclebasis: unknown extension'

		self.runner.set_initial_circuit(g)
		self.runner.set_initial_choices(set(g) - set(config.get_no_defect()))
		self.runner.set_initial_cycles(cycles)
		self.runner.set_measured_edge(*config.get_measured_edge())

	def set_order(self, fname):
		import json
		with open(RESOURCE(fname)) as f:
			arr = json.load(f)

		# Trial runner currently uses a fixed number of substeps per step,
		#  while the .order format technically permits the amount to vary
		#  from step to step. Require consistent amounts.
		# (note: last amount is allowed to be different; the trial runner
		#  will simply end early)
		substeps = len(arr[0])
		assert all(len(x) == substeps for x in arr[:-1]), ".order file has inconsistent substep count"

		# A selection mode specially built for replays like this.
		smode = node_selection.fixed_order(flat(arr))

		self.runner.set_defects_per_step(substeps)
		self.runner.set_selection_mode(smode)

	def set_output(self, fname):
		self.output_path = RESOURCE(fname)

	#-----------------------

	# using the name "do_it" in an attempt not to step on unittest's or nosetests's toes
	# (unittest has a "run" method, and nosetest tries to run "run_test")
	def do_it(self, sigfigs=7):
		import json
		if not hasattr(self, 'output_path'):
			assert False, 'test forgot to call set_output'

		old_path = self.output_path
		new_path = self.output_path + '.new'

		# Generate a new output before anything else.
		# This way a newly written trial can be "bootstrapped" by running it once
		#   with no output file and renaming the new output file.
		new_data = self.runner.run_trial()['steps']['current']
		with open(new_path, 'wt') as f:
			json.dump(new_data, f, indent=1) # use indent to prettify

		# Acquire expected output
		try:
			with open(old_path) as f:
				old_data = json.load(f)
		except FileNotFoundError as e:
			print("No expected output file found at '{}'".format(old_path))
			print("It appears this is a new test.")
			print("New output has been written to '{}'".format(new_path))
			print("If it is correct, you may use it as the expected output file by renaming it.")
			assert False, 'please see message written to stdout'

		# Compare actual output to expected
		self.assertEqual(len(old_data), len(new_data), "ran wrong number of steps")
		for i,(o,n) in enumerate(zip(old_data, new_data)):

			# assertAlmostEqual does an absolute magnitude check.
			# Because current may change by orders of magnitude over the course of the test,
			#  we'd prefer a relative magnitude test.
			delta = 10**(-sigfigs) * min(abs(o), abs(n))
			self.assertAlmostEqual(o, n, delta=delta, msg='current mismatch at step {}'.format(i))

		# Signify to the tearDown check that the test has indeed been run
		self.test_has_run = True

	#-----------------------

	def test_multiply(self):
		# tests consistency of results from multiply mode
		self.set_input('square10', 'square10.planar.gpos')
		self.set_order('square10-general.order')
		self.set_output('square10-m100.output')
		self.runner.set_deletion_mode(
			node_deletion.multiply_resistance(factor=100., idempotent=False, radius=1)
		)
		self.do_it()

	def test_assign(self):
		# tests consistency of results from assign mode
		self.set_input('square10', 'square10.planar.gpos')
		self.set_order('square10-general.order')
		self.set_output('square10-a100.output')
		self.runner.set_deletion_mode(
			node_deletion.multiply_resistance(factor=100., idempotent=True, radius=1)
		)
		self.do_it()

	def test_failing_test(self):
		# use the wrong output file, make sure the test fails
		self.set_input('square10', 'square10.planar.gpos')
		self.set_order('square10-general.order')
		self.set_output('square10-m100.output')  # output for 'multiply' mode...
		self.runner.set_deletion_mode(
			# but test using 'assign' mode
			node_deletion.multiply_resistance(factor=100., idempotent=True, radius=1)
		)
		self.assertRaisesRegexp(AssertionError, 'current mismatch', self.do_it)
		self.test_has_run = True  # the above line counts as the test

	def test_remove_full(self):
		# tests consistency of results from remove mode
		self.set_input('square10', 'square10.planar.gpos')
		self.set_order('square10-general.order')
		self.set_output('square10-rem-full.output')
		self.runner.set_deletion_mode(
			node_deletion.annihilation(radius=1)
		)
		self.runner.set_end_on_disconnect(False)
		self.do_it()

	def test_remove_eod(self):
		# tests ending on disconnect
		self.set_input('square10', 'square10.planar.gpos')
		self.set_order('square10-general.order')
		self.set_output('square10-rem-disconnect.output') # same as '-full' but stops at first zero
		self.runner.set_deletion_mode(
			node_deletion.annihilation(radius=1)
		)
		self.runner.set_end_on_disconnect(True)
		self.do_it()

def flat(it):
	for x in it:
		yield from x

if __name__ == '__main__':
	run_trial_tests()
