
from abc import ABCMeta, abstractmethod

import numpy as np

__all__ = [
	'AbstractModel',
	'LinearModel',
	'PowerLawModel',
]

class AbstractModel(metaclass=ABCMeta):
	'''
	A function in one variable which can be fit from x/y data.
	'''

	@abstractmethod
	def apply(self, x):
		'''
		Evaluates the function.

		Implementations are expected to support numpy arrays in addition
		to scalars.  If writing a numpy-compatible implementation is too
		difficult, note that one can be automatically generated by
		decorating the definition with ``@numpy.vectorize``.
		'''
		pass

	@classmethod
	@abstractmethod
	def from_data(cls, x, y):
		'''
		Produces an instance of the model that best fits the data.

		Arguments:
			x, y:  iterables
		'''
		pass

	def __call__(self, x):
		'''
		Evaluates the function.
		'''
		return self.apply(x)

	# NOTE: not sure whether or not to include __format__ here as it might end up
	#        a de facto part of the interface anyways

class LinearModel(AbstractModel):
	'''
	Represents a function of the form ``f(x) = a * x + b``
	'''

	def __init__(self, slope, offset):
		assert isinstance(slope, float)
		assert isinstance(offset, float)
		self.slope = slope
		self.offset = offset

	def apply(self, x):
		return self.slope * x + self.offset

	@classmethod
	def from_data(cls, x, y):
		slope, offset = np.polyfit(x,y,1)
		return cls(slope, offset)

	def __format__(self, format_spec):
		''' Applies the format spec to each parameter. '''
		pat = make_pattern('# x + #', '#', format_spec)
		return pat.format(self.slope, self.offset)

	def __str__(self):
		return self.__format__('')

	def __repr__(self):
		return '{}({}, {})'.format(type(self).__name__, self.slope, self.offset)


class PowerLawModel(AbstractModel):
	'''
	Represents a function of the form ``f(x) = a * x**k``
	'''

	def __init__(self, coeff, power):
		assert isinstance(coeff, float)
		assert isinstance(power, float)
		self.coeff = coeff
		self.power = power

	def apply(self, x):
		return self.coeff * np.power(x, self.power)

	@classmethod
	def from_data(cls, x, y):
		x = np.log(np.array(x))
		y = np.log(np.array(y))
		slope, offset = np.polyfit(x,y,1)

		coeff = np.exp(offset)
		power = slope
		return cls(coeff, power)

	def __format__(self, format_spec):
		''' Applies the format spec to each parameter. '''
		pat = make_pattern('# x ** #', '#', format_spec)
		return pat.format(self.coeff, self.power)

	def __str__(self):
		return self.__format__('')

	def __repr__(self):
		return '{}({}, {})'.format(type(self).__name__, self.coeff, self.power)


def make_pattern(s, seq, format_spec):
	'''
	Makes a format pattern where all args share a format spec.
	'''
	return s.replace(seq, '{:%s}' % (format_spec,))
