import builtins
from inspect import signature
from collections.abc import Iterable
import numpy as np

# Interesting Fact: The numpy arrayprint machinery (for one) depends on having
# a separate scalar type associated with any new ducktype (or subclass). This
# is partly why both MaskedArray and recarray have to define associated scalar
# types. I don't currently see a way to avoid this: All ducktypes will need
# to create a scalar type, and return it (and not a 0d array) when indexed with
# an integer.

#XXX consider defining an abstract "duck_scalar" class which all duck-scalar
# implementors would be required to inherit. Then the function below could
#be coded as "isinstance(val, [np.generic, duck_scalar])". On the other hand,
# using inheritance partly defeats point of ducktypes.

# should numpy make its scalars support array_function?

def is_ndducktype(val):
    return hasattr(val, '__array_function__')

def is_ndscalar(val):
    # These files assume that a scalar is a type separate from the main ducktype
    # which also has an __array_function__ attribute.
    return (isinstance(val, np.generic) or (not isinstance(val, np.ndarray) and
            is_ndducktype(val) and type(val) == val._scalartype))

def is_ndarr(val):
    return is_ndducktype(val) and not is_ndscalar(val)

def is_ndtype(val):
    return is_ndducktype(val) or isinstance(val, np.generic)


class _implements:
    """
    Register an __array_function__ method for a ducktype implementation.

    checked_args : iterable of strings, function. optional
        If not provided, all entries in the "types" list from numpy
        dispatch are checked to be of known class.

        If an iterable of argument names, those arguments are checked to be of
        known class if supplied.

        If a function, should take four arguments, (args, kwds, types,
        known_types) where args, kwds, types are the same as supplied to
        __array_function__, and "known_types" is a list of compatible types. An
        iterable of types may be returned to be checked to be of known class,
        or None to signify all args were checked, or a NotImplementedError may
        be raised to signal no match.

    Notes
    -----
    Goal is to allow both control and convenience. The callable form of
    checked_args is most powerful since it can be used to implement any
    desired behavior based purely on the dispatch "args" by raising
    NotImplementedError. This includes the behaviors obtained by giving a
    callable return an iterable of , of using a tuple, or not providing
    checked_args, so these latter forms are for convenience only.
    """
    def __init__(self, numpy_function, checked_args=None):
        self.npfunc = numpy_function
        self.checked_args = checked_args

    @classmethod
    def check_types(cls, types, known_types):
        # returns true if all types are known types or ndarray/scalar.
        return builtins.all((issubclass(t, known_types) or
                             t is np.ndarray or np.isscalar(t)) for t in types)

    def __call__(self, func):
        checked_args = self.checked_args

        if isinstance(checked_args, Iterable):
            sig = signature(func)
            def checked_args_func(args, kwargs, types, known_types):
                bound = sig.bind(*args, **kwargs).arguments
                args = (bound.get(a, None) for a in checked_args)
                types = (type(v) for v in args if v not in (None, np._NoValue))
                return self.check_types(types, known_types)

        elif callable(checked_args):
            def checked_args_func(args, kwargs, types, known_types):
                try:
                    types = checked_args(args, kwargs, types, known_types)
                except NotImplementedError:
                    return False
                if types is None:
                    return True
                return self.check_types(types, known_types)

        elif checked_args is None:
            checked_args_func = lambda a, k, t, n: self.check_types(t, n)

        else:
            raise ValueError("invalid checked_args")

        self.handled_functions[self.npfunc] = (func, checked_args_func)

        return func

def new_ducktype_implementation():
    class new_impl(_implements):
        handled_functions = {}
        def __init__(self, numpy_function, checked_args=None):
            super().__init__(numpy_function, checked_args)

    return new_impl

def ducktype_link(arraytype, scalartype, known_types=None):
    arraytype._arraytype = scalartype._arraytype = arraytype
    arraytype._scalartype = scalartype._scalartype = scalartype
    known = (arraytype, scalartype, np.ndarray)
    if known_types is not None:
        known += tuple(known_types)
    arraytype.known_types = scalartype.known_types = known

def get_duck_cls(*args, base=None):
    """
    Helper to make ducktypes Subclass-friendly.

    Finds the most derived class of a ducktype
    If given both an Array and a Scalar, convert the Scalar to an array first.

    In the cast of two non-inheriting ducktypes (or ndarray itself), if
    one ducktype is in the known_types of the other, and not vice-versa,
    the class of the latter supersedes. If neither, or both, of the ducktypes
    is within the known_types of the other, raise TypeError.

    All of the ducktypes must support the _arraytype/_scalartype and known_types
    attributes used by the ndarray_ducktypes module.

    Parameters
    ==========
    *args : nested list/tuple or ndarray ducktype
        The bottom elements can be either ndarrays, scalars, ducktypes of
        either, or type objects of any of these.

    Returns
    =======
    arraytype : type
        The derived class of all of the inputs
    """
    cls = base
    for arg in args:
        if is_ndtype(arg):
            if isinstance(arg, (np.ndarray, np.generic)):
                acl = np.ndarray
            else:
                acl = arg._arraytype

            # TODO: tidy up this logic?
            if cls is None or cls == np.ndarray or issubclass(acl, cls):
                cls = acl
            elif acl != np.ndarray and not issubclass(cls, acl):
                if cls in acl.known_types:
                    cls = acl
                elif acl in cls.known_types:
                    pass
                else:
                    raise TypeError(("Ambiguous mix of ducktypes {} and {}"
                                    ).format(cls, acl))
        elif isinstance(arg, (list, tuple)):
            tmpcls = get_duck_cls(*arg)
            if tmpcls is not None and (cls is None or issubclass(cls, tmpcls)):
                cls = tmpcls

    if cls is None:
        return None
    return cls

def as_duck_cls(*args, base=None, single=True):
    # single=True means return the arg if only 1 arg. i
    # single=False always returns a tuple.
    cls = get_duck_cls(*args, base)
    if single and len(args) == 1:
        a = args[0]
        return cls(a) if type(a) != cls else a
    return tuple(cls(a) if type(a) != cls else a for a in args)
