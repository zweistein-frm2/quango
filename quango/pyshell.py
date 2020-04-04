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
#   Alexander Lenz <alexander.lenz@frm2.tum.de>
#
# *****************************************************************************

"""NICOS GUI debug console window."""

import codeop
import sys
import traceback

from quango.qt import QCoreApplication, QFont, QMainWindow, QPlainTextEdit, \
    Qt, QTextCursor, QTextOption, pyqtSignal

try:
    from qtconsole.rich_jupyter_widget import RichJupyterWidget
    from qtconsole.inprocess import QtInProcessKernelManager
    ipythonAvailable = True

    # IPython

    class QIPythonWidget(RichJupyterWidget):
        """Convenience class for a live IPython console widget."""

        closeRequested = pyqtSignal()

        def __init__(self, parent, custom_banner=None):
            if custom_banner is not None:
                self.banner = custom_banner
            super(QIPythonWidget, self).__init__(parent)
            self.kernel_manager = kernel_manager = QtInProcessKernelManager()
            kernel_manager.start_kernel()
            kernel_manager.kernel.gui = 'qt4'
            self.kernel_client = kernel_client = self._kernel_manager.client()
            kernel_client.start_channels()

            def stop():
                kernel_client.stop_channels()
                kernel_manager.shutdown_kernel()
                self.closeRequested.emit()

            self.exit_requested.connect(stop)

        def pushVariables(self, variable_dict):
            """Given a dictionary containing name / value pairs, push those
            variables to the IPython console widget.
            """
            self.kernel_manager.kernel.shell.push(variable_dict)

        def clearTerminal(self):
            """Clears the terminal."""
            self._control.clear()

        def printText(self, text):
            """Prints some plain text to the console."""
            self._append_plain_text(text)

        def executeCommand(self, command):
            """Execute a command in the frame of the console widget."""
            self._execute(command, True)

except ImportError:
    ipythonAvailable = False


# Raw Python

class StdoutProxy(object):
    def __init__(self, write_func):
        self.write_func = write_func
        self.skip = False

    def write(self, text):
        if not self.skip:
            stripped_text = text.rstrip('\n')
            self.write_func(stripped_text)
            QCoreApplication.processEvents()
        self.skip = not self.skip


class ConsoleBox(QPlainTextEdit):
    closeRequested = pyqtSignal()

    def __init__(self, ps1='>>> ', ps2='... ', startup_message='', parent=None):
        QPlainTextEdit.__init__(self, parent)
        self.ps1, self.ps2 = ps1, ps2
        self.history = []
        self.namespace = {}
        self.construct = []
        self.compiler = codeop.CommandCompiler()
        self.stdout = StdoutProxy(self.appendPlainText)

        self.setWordWrapMode(QTextOption.WrapAnywhere)
        self.setUndoRedoEnabled(False)
        self.document().setDefaultFont(QFont("monospace", 10, QFont.Normal))
        self.showMessage(startup_message)

    def showMessage(self, message):
        oldcommand = self.getCommand()
        self.appendPlainText(message)
        self.newPrompt()
        if oldcommand:
            self.setCommand(oldcommand)

    def newPrompt(self):
        if self.construct:
            prompt = self.ps2
        else:
            prompt = self.ps1
        self.appendPlainText(prompt)
        self.moveCursor(QTextCursor.End)

    def getCommand(self):
        doc = self.document()
        curr_line = doc.findBlockByLineNumber(doc.lineCount() - 1).text()
        return curr_line[len(self.ps1):]

    def setCommand(self, command):
        if self.getCommand() == command:
            return
        self.moveCursor(QTextCursor.End)
        self.moveCursor(QTextCursor.StartOfLine, QTextCursor.KeepAnchor)
        for _ in range(len(self.ps1)):
            self.moveCursor(QTextCursor.Right, QTextCursor.KeepAnchor)
        self.textCursor().removeSelectedText()
        self.textCursor().insertText(command)
        self.moveCursor(QTextCursor.End)

    def getConstruct(self, command):
        res = self.compiler('\n'.join(self.construct + [command]),
                            '<interactive>', 'single')
        if res is not None:
            self.construct = []
        else:
            self.construct.append(command)
        return res

    def addToHistory(self, command):
        if command and (not self.history or self.history[-1] != command):
            self.history.append(command)
        self.history_index = len(self.history)

    def getPrevHistoryEntry(self):
        if self.history:
            self.history_index = max(0, self.history_index - 1)
            return self.history[self.history_index]
        return ''

    def getNextHistoryEntry(self):
        if self.history:
            hist_len = len(self.history)
            self.history_index = min(hist_len, self.history_index + 1)
            if self.history_index < hist_len:
                return self.history[self.history_index]
        return ''

    def getCursorPosition(self):
        return self.textCursor().columnNumber() - len(self.ps1)

    def setCursorPosition(self, position):
        self.moveCursor(QTextCursor.StartOfLine)
        for _ in range(len(self.ps1) + position):
            self.moveCursor(QTextCursor.Right)

    def runCommand(self):
        command = self.getCommand()
        self.addToHistory(command)

        tmp_stdout = sys.stdout
        sys.stdout = self.stdout
        try:
            command = self.getConstruct(command)
            if not command:
                return
            exec(command, self.namespace)
        except SystemExit:
            self.closeRequested.emit()
        except:  # pylint: disable=W0702
            traceback_lines = traceback.format_exc().split('\n')
            # Remove traceback mentioning this file, and a linebreak
            for i in (2, 1, -1):
                traceback_lines.pop(i)
            self.appendPlainText('\n'.join(traceback_lines))
        finally:
            sys.stdout = tmp_stdout
        self.newPrompt()

    def pushVariables(self, variable_dict):
        self.namespace.update(variable_dict)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            self.runCommand()
            return
        if event.key() == Qt.Key_Home:
            self.setCursorPosition(0)
            return
        if event.key() == Qt.Key_PageUp:
            return
        elif event.key() in (Qt.Key_Left, Qt.Key_Backspace):
            if self.getCursorPosition() == 0:
                return
        elif event.key() == Qt.Key_Up:
            self.setCommand(self.getPrevHistoryEntry())
            return
        elif event.key() == Qt.Key_Down:
            self.setCommand(self.getNextHistoryEntry())
            return
        elif event.key() == Qt.Key_D and event.modifiers() == Qt.ControlModifier:
            self.closeRequested.emit()
        super(ConsoleBox, self).keyPressEvent(event)


class ConsoleWindow(QMainWindow):
    def __init__(self, title, ns=None, banner='', parent=None):
        QMainWindow.__init__(self, parent)
        self.setWindowTitle(title)

        if ipythonAvailable:
            self.shell = QIPythonWidget(self, banner)
        else:
            self.shell = ConsoleBox()
            self.shell.showMessage(banner)

        self.shell.closeRequested.connect(self.close)

        self.setCentralWidget(self.shell)
        self.shell.pushVariables(ns or {})
