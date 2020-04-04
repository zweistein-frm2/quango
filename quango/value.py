#  -*- coding: utf-8 -*-
# *****************************************************************************
# MLZ Tango client tool
# Copyright (c) 2015-2019 by the authors, see LICENSE
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Module authors:
#   Georg Brandl <g.brandl@fz-juelich.de>
#
# *****************************************************************************

import re

import numpy
import PyTango
import six
from PyTango import CmdArgType as Type, utils

QUOTED_STRING = re.compile(r'''
    \s* (                    # leading whitespace
    ( [^"'] [^,]*? ) |       # unquoted string: non-quote, then anything
    (?: (["']) ((?:\\\\|\\"|\\'|[^"])*) \3 )
                             # quoted string: quote, content, quote
    \s* ) (?=,|$)            # trailing whitespace, comma or end of string
    ''', re.X)

array_to_scalar_type = {
    Type.DevVarCharArray:    Type.DevUChar,
    Type.DevVarShortArray:   Type.DevShort,
    Type.DevVarLongArray:    Type.DevLong,
    Type.DevVarFloatArray:   Type.DevFloat,
    Type.DevVarDoubleArray:  Type.DevDouble,
    Type.DevVarUShortArray:  Type.DevUShort,
    Type.DevVarULongArray:   Type.DevULong,
    Type.DevVarStringArray:  Type.DevString,
    Type.DevVarBooleanArray: Type.DevBoolean,
    Type.DevVarLong64Array:  Type.DevLong64,
    Type.DevVarULong64Array: Type.DevULong64,
}


def match_string(instr):
    if not instr:
        raise ValueError('empty string must be given with quotes')
    m = QUOTED_STRING.match(instr)
    if not m:
        raise ValueError('invalid quoted or unquoted string: %r' % instr)
    if m.group(2) is not None:
        # unquoted
        return m.group(2).strip(), m.end()
    return str(m.group(4).decode('string-escape')), m.end()


def match_string_array(instr):
    instr = instr.strip()
    if not (instr.startswith('[') and instr.endswith(']')):
        raise ValueError('arrays must be comma-separated and enclosed '
                         'in brackets')
    instr = instr[1:-1].strip()
    elements = []
    while instr:
        el, end = match_string(instr)
        elements.append(el)
        instr = instr[end:].lstrip()
        if instr and not instr.startswith(','):
            raise ValueError('arrays must be comma-separated and enclosed '
                             'in brackets')
        instr = instr[1:].strip()
    return elements


def match_num_array(instr, tgtype):
    instr = instr.strip()
    if not (instr.startswith('[') and instr.endswith(']')):
        raise ValueError('arrays must be comma-separated and enclosed '
                         'in brackets')
    instr = instr[1:-1]
    return [from_input_string(tgtype, v.strip())
            for v in instr.split(',') if v]


def match_string_x_array(instr, tgtype):
    instr = instr.strip()
    if not (instr.startswith('[') and instr.endswith(']')):
        raise ValueError('arrays must be comma-separated and enclosed '
                         'in brackets')
    num_start = instr.rindex('[')
    if num_start == 0:
        raise ValueError('string-number arrays must be typed like this: '
                         '[a,b][1,2]')
    num_array = match_num_array(instr[num_start:], tgtype)
    str_array = match_string_array(instr[:num_start])
    if len(num_array) != len(str_array):
        raise ValueError('string-number arrays must have equal number '
                         'of items')
    return (num_array, str_array)


def from_input_string(tgtype, instr):
    try:
        return from_input_string_inner(tgtype, instr)
    except ValueError as err:
        raise ValueError('Invalid input value: %s.' % err)


def from_input_string_inner(tgtype, instr):
    if tgtype is Type.DevVoid:
        return None
    elif tgtype is Type.DevBoolean:
        if instr in ('1', 'true', 'True'):
            return True
        elif instr in ('0', 'false', 'False'):
            return False
        else:
            raise ValueError('cannot convert to bool: %r' % instr)
    elif tgtype in (
            Type.DevShort, Type.DevInt, Type.DevLong, Type.DevLong64,
            Type.DevUChar, Type.DevUShort, Type.DevULong, Type.DevULong64):
        if instr.startswith('\'') and instr.endswith('\''):
            s = match_string(instr)[0]
            if len(s) == 1:
                return ord(s)
            raise ValueError('cannot convert to single integer: %r' % s)
        return int(instr, 0)
    elif tgtype in (Type.DevDouble, Type.DevFloat):
        return float(instr)
    elif tgtype is Type.DevState:
        for stname, stval in PyTango.DevState.names.items():
            if instr.lower() == stname.lower():
                return stval
        raise ValueError('cannot convert to DevState: %r' % instr)
    elif tgtype in (Type.ConstDevString, Type.DevString):
        if six.PY2:
            instr = instr.encode('latin1') \
                if isinstance(instr, six.text_type) else str(instr)
        if instr.startswith(('"', "'")):
            return match_string(instr)[0]
        return instr
    elif tgtype is Type.DevVarStringArray:
        if six.PY2:
            instr = instr.encode('latin1') \
                if isinstance(instr, six.text_type) else str(instr)
        return match_string_array(instr)
    elif tgtype is Type.DevEncoded:
        raise ValueError('type %s not supported yet' % tgtype)
    elif tgtype is Type.DevVarLongStringArray:
        return match_string_x_array(instr, Type.DevLong)
    elif tgtype is Type.DevVarDoubleStringArray:
        return match_string_x_array(instr, Type.DevDouble)
    else:
        return match_num_array(instr, array_to_scalar_type[tgtype])


def to_presentation_inline(tgtype, tgval, alt=False):
    if tgtype is Type.DevVarDoubleStringArray:
        return (to_presentation_inline(Type.DevVarStringArray, tgval[1]) +
                to_presentation_inline(Type.DevVarDoubleArray, tgval[0]))
    elif tgtype is Type.DevVarLongStringArray:
        return (to_presentation_inline(Type.DevVarStringArray, tgval[1]) +
                to_presentation_inline(Type.DevVarLongArray, tgval[0]))
    elif utils.is_array_type(tgtype):
        scalar_type = array_to_scalar_type[tgtype]
        if len(tgval) > 6:
            rv = ('[' +
                  ', '.join(to_presentation_inline(scalar_type, val)
                            for val in tgval[:3]) +
                  ', ..., ' +
                  ', '.join(to_presentation_inline(scalar_type, val)
                            for val in tgval[-3:]) +
                  '] (%d items)' % len(tgval))
        else:
            rv = '[' + ', '.join(to_presentation_inline(scalar_type, val)
                                 for val in tgval) + ']'
            if alt:
                rv += ' (%d items)' % len(tgval)
        return rv
    elif tgtype is Type.DevVoid:
        return ''
    elif tgtype in (Type.ConstDevString, Type.DevString):
        return repr(tgval)
    elif isinstance(tgval, six.integer_types) and alt:
        return '{0}    ({0:#x}, {0:#o}, {0:#b})'.format(tgval)
    return str(tgval)


def shortening_iter(seq):
    if len(seq) > 256:
        for v in enumerate(seq[:128]):
            yield v
        yield -1, '...'
        for v in enumerate(seq[-128:], start=len(seq)-128):
            yield v
    else:
        for v in enumerate(seq):
            yield v
    if len(seq) > 6 and isinstance(seq, numpy.ndarray):
        yield -1, 'sum = %s' % seq.sum()


def to_presentation_multiline(tgtype, tgval, alt=False):
    if not utils.is_array_type(tgtype):
        return to_presentation_inline(tgtype, tgval, alt)
    if len(tgval) == 0:
        return '<empty array>'
    ret = []
    if tgtype is Type.DevVarDoubleStringArray:
        for i, val in shortening_iter(list(map(None, tgval[0], tgval[1]))):
            if i == -1:
                ret.append(val)
                continue
            ret.append(
                '[%2d] %s : %s' %
                (i, to_presentation_inline(Type.DevString, val[1], alt),
                 to_presentation_inline(Type.DevDouble, val[0], alt)))
    elif tgtype is Type.DevVarLongStringArray:
        for i, val in shortening_iter(list(map(None, tgval[0], tgval[1]))):
            if i == -1:
                ret.append(val)
                continue
            ret.append(
                '[%2d] %s : %s' %
                (i, to_presentation_inline(Type.DevString, val[1], alt),
                 to_presentation_inline(Type.DevLong, val[0], alt)))
    else:
        for i, val in shortening_iter(tgval):
            if i == -1:
                ret.append(val)
                continue
            ret.append('[%2d] %s' % (i, to_presentation_inline(
                array_to_scalar_type[tgtype], val, alt)))
    return '\n'.join(ret)
