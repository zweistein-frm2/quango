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

"""A line editor control with history stepping."""

import re

from quango.qt import QApplication, QKeyEvent, QLineEdit, Qt

wordsplit_re = re.compile(r'[ \t\n\"\\\'`@$><=;|&{(\[]')


class HistoryLineEdit(QLineEdit):
    """A line edit with history stepping."""

    scrollingKeys = [Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown]

    def __init__(self, parent, history=None):
        QLineEdit.__init__(self, parent)
        self.history = history or []
        self.scrollWidget = None
        self.control = False
        self._start_text = ''
        self._current = -1

    def keyPressEvent(self, kev):
        key_code = kev.key()

        # if it's a shifted scroll key...
        if kev.modifiers() & Qt.ShiftModifier and \
                self.scrollWidget and \
                key_code in self.scrollingKeys:
            # create a new, unshifted key event and send it to the
            # scrolling widget
            nev = QKeyEvent(kev.type(), kev.key(), Qt.NoModifier)
            QApplication.sendEvent(self.scrollWidget, nev)
            return

        if key_code == Qt.Key_Escape:
            # abort history search
            self.setText(self._start_text)
            self._current = -1
            QLineEdit.keyPressEvent(self, kev)

        elif key_code == Qt.Key_Up:
            # go earlier
            if self._current == -1:
                self._start_text = self.text()
                self._current = len(self.history)
                # if the last history element is the same as the current text,
                # step one more
                if self.history and self.history[-1] == self._start_text:
                    self._current -= 1
            self.stepHistory(-1)
        elif key_code == Qt.Key_Down:
            # go later
            if self._current == -1:
                return
            self.stepHistory(1)

        elif key_code == Qt.Key_PageUp:
            # go earlier with prefix
            if self._current == -1:
                self._current = len(self.history)
                self._start_text = self.text()
            prefix = self.text()[:self.cursorPosition()]
            self.stepHistoryUntil(prefix, 'up')

        elif key_code == Qt.Key_PageDown:
            # go later with prefix
            if self._current == -1:
                return
            prefix = self.text()[:self.cursorPosition()]
            self.stepHistoryUntil(prefix, 'down')

        elif key_code in (Qt.Key_Return, Qt.Key_Enter):
            # accept - add to history and do normal processing
            self._current = -1
            text = self.text()
            if text and (not self.history or self.history[-1] != text):
                # append to history, but only if it isn't equal to the last
                self.history.append(text)
            self.control = bool(kev.modifiers() & Qt.ControlModifier)
            QLineEdit.keyPressEvent(self, kev)

        else:
            # process normally
            QLineEdit.keyPressEvent(self, kev)

    def stepHistory(self, num):
        self._current += num
        if self._current <= -1:
            # no further
            self._current = 0
            return
        if self._current >= len(self.history):
            # back to start
            self._current = -1
            self.setText(self._start_text)
            return
        self.setText(self.history[self._current])

    def stepHistoryUntil(self, prefix, direction):
        if direction == 'up':
            lookrange = range(self._current - 1, -1, -1)
        else:
            lookrange = range(self._current + 1, len(self.history))
        for i in lookrange:
            if self.history[i].startswith(prefix):
                self._current = i
                self.setText(self.history[i])
                self.setCursorPosition(len(prefix))
                return
        if direction == 'down':
            # nothing found: go back to start
            self._current = -1
            self.setText(self._start_text)
            self.setCursorPosition(len(prefix))
