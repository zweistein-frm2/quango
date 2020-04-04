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

from PyTango import CmdArgType

from quango.value import from_input_string, to_presentation_inline, \
    to_presentation_multiline


def test_string_input():
    def f(s):
        return from_input_string(CmdArgType.DevString, s)

    # unquoted
    assert f('abc') == 'abc'
    assert f(' abc ') == ' abc '
    assert f('ab"c') == 'ab"c'

    # quoted
    assert f('"abc"') == 'abc'
    assert f('"ab,c,d"') == 'ab,c,d'
    assert f('"\\r\\n\\x00"') == '\r\n\x00'
    assert f('"\\""') == '"'


def test_string_array():
    def f(s):
        return from_input_string(CmdArgType.DevVarStringArray, s)

    assert f('[]') == []
    assert f('[a,b,c]') == ['a', 'b', 'c']
    assert f('[ a, b , c ]') == ['a', 'b', 'c']
    assert f('["a","b","c,d"]') == ['a', 'b', 'c,d']

    # invalid
    for instr in ['a,b,c', '', '[d,']:
        try:
            f(instr)
        except ValueError:
            pass
        else:
            assert False


def test_num_array():
    assert from_input_string(CmdArgType.DevVarBooleanArray, '[false,0,1]') == \
        [False, False, True]
    assert from_input_string(CmdArgType.DevVarDoubleArray, '[]') == []
    assert from_input_string(CmdArgType.DevVarLongArray, '[0,5]') == [0, 5]


def test_special_arrays():
    assert from_input_string(CmdArgType.DevVarDoubleStringArray, '[][]') == ([], [])
    assert from_input_string(CmdArgType.DevVarDoubleStringArray, '["a][",b][1.0,2.0]') == \
        ([1.0, 2.0], ['a][', 'b'])

    # invalid
    for instr in ['[a][1,2]']:
        try:
            from_input_string(CmdArgType.DevVarDoubleStringArray, instr)
        except ValueError:
            pass
        else:
            assert False


def test_to_presentation():
    assert to_presentation_inline(CmdArgType.DevBoolean, False) == 'False'
    assert to_presentation_inline(CmdArgType.DevVoid, None) == ''
    assert to_presentation_inline(CmdArgType.DevLong, 5) == '5'
    assert to_presentation_inline(CmdArgType.DevString, 'a\n') == '\'a\\n\''
    assert to_presentation_inline(CmdArgType.DevVarLongArray, [0, 1]) == '[0, 1]'
    assert to_presentation_inline(CmdArgType.DevVarLongStringArray, ([0, 1], ['a', 'b'])) == \
        '[\'a\', \'b\'][0, 1]'

    assert to_presentation_multiline(CmdArgType.DevVarLongArray, []) == '<empty array>'
    assert to_presentation_multiline(CmdArgType.DevVarLongArray, [1, 2, 3]) == \
        '[ 0] 1\n[ 1] 2\n[ 2] 3'
    assert to_presentation_multiline(CmdArgType.DevVarLongStringArray, ([1, 2, 3], ['a', 'b', 'c'])) == \
        '[ 0] \'a\' : 1\n[ 1] \'b\' : 2\n[ 2] \'c\' : 3'
