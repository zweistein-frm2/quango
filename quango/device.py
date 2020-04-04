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

import time

from quango.qt import QApplication, QColor, QLabel, QListWidgetItem, \
    QMessageBox, QPalette, QPixmap, QSettings, Qt, QTextCursor, QTimer, \
    QWidget, pyqtSignal, pyqtSlot

import PyTango

from quango.mlzgui import INTERFACES
from quango.utils import displayTangoError, getPreferences, loadUi, \
    onelineExcDesc, setForegroundColor, simpleExcDesc
from quango.value import from_input_string, to_presentation_inline, \
    to_presentation_multiline

try:
    from html import escape as escape_html  # pylint: disable=import-error
except ImportError:
    from cgi import escape as escape_html




class GenericCmdAttrWidget(QWidget):

    CMD_ITEM = QListWidgetItem.UserType + 1
    ATTR_ITEM = QListWidgetItem.UserType + 2

    def __init__(self, parent, proxy, fulladdr):
        QWidget.__init__(self, parent)
        loadUi(self, 'gencmdattrwidget.ui')

        self._cmds = {}
        self._attrs = {}
        self.proxy = proxy
        self.fulladdr = fulladdr
        self._prefSrc = None

        settings = QSettings()
        settings.beginGroup(fulladdr)
        history = settings.value('history', [])
        self.arginLineEdit.history = history or []
        self.arginLineEdit.scrollWidget = self.outputTextBrowser

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.writeBtn.setVisible(False)
        self.readBtn.setVisible(False)
        self.pollBtn.setEnabled(False)
        self.pollArea.hide()
        self.helpLbl.hide()
        self.execBtn.setEnabled(False)
        self._fillListWidget()

        for entry in QApplication.instance().topLevelWidgets():
            if hasattr(entry, 'preferencesChanged'):
                self._prefSrc = entry
                break

    def saveHistory(self):
        settings = QSettings()
        settings.beginGroup(self.fulladdr)
        settings.setValue('history', self.arginLineEdit.history[-100:])

    # -- SLOTS --

    def on_arginLineEdit_returnPressed(self):
        self._execAction(self.arginLineEdit.control)

    @pyqtSlot()
    def on_execBtn_clicked(self):
        self._execAction()

    @pyqtSlot()
    def on_readBtn_clicked(self):
        self._readAttr()

    @pyqtSlot()
    def on_writeBtn_clicked(self):
        self._writeAttr()

    @pyqtSlot()
    def on_pollBtn_clicked(self):
        if self._isAlreadyPolled():
            self._stopPoll()
        else:
            self._startPoll()

    @pyqtSlot()
    def on_clearBtn_clicked(self):
        self.outputTextBrowser.clear()

    def on_outputTextBrowser_anchorClicked(self, url):
        target, tgtype, value = url.toString().split(':', 2)
        tgtype = PyTango.CmdArgType.values[int(tgtype)]

        action_item = self.actionListWidget.findItems('  ' + target,
                                                      Qt.MatchFixedString)[0]
        self.actionListWidget.setCurrentItem(action_item)
        if tgtype == PyTango.CmdArgType.DevString and eval(value) == value[1:-1]:
            self.arginLineEdit.setText(value[1:-1])
        else:
            self.arginLineEdit.setText(value)
        self.arginLineEdit.setFocus()

    def on_helpBtn_toggled(self, on):
        self.helpLbl.setVisible(on)

    def _genHelp(self):
        def prepare(s):
            if s == 'Uninitialised':
                return ''
            return '<br/>' + escape_html(s)
        item = self.actionListWidget.currentItem()
        if not item:
            return
        name = self._getCurItemText()
        if item.type() == self.CMD_ITEM:
            cmd = self._cmds[name]
            self.helpLbl.setText(
                '''
                <p><b>Command:</b> %s</p>
                <p><b>Input argument:</b> <i>%s</i> %s</p>
                <p><b>Return value:</b> <i>%s</i> %s</p>
                ''' % (cmd.cmd_name,
                       cmd.in_type, prepare(cmd.in_type_desc),
                       cmd.out_type, prepare(cmd.out_type_desc)))
        elif item.type() == self.ATTR_ITEM:
            attr = self._attrs[name]
            self.helpLbl.setText(
                '''
                <p><b>Attribute:</b> %s</p>
                <p><b>Documentation:</b> %s</p>
                <p><b>Data type:</b> <i>%s</i> (%s)</p>
                <p><b>Unit:</b> %s</p>
                ''' % (attr.name, prepare(attr.description),
                       self._getAttrType(name), attr.data_format,
                       attr.unit))

    def on_actionListWidget_itemDoubleClicked(self, _):
        self._execAction()

    def on_actionListWidget_currentItemChanged(self, item, _):
        if item.type() == self.CMD_ITEM:
            self.execBtn.show()
            self.writeBtn.hide()
            self.readBtn.hide()
            argtype = self._cmds[self._getCurItemText()].in_type
            self.pollBtn.setEnabled(True)
            self.argTypeLabel.setText('Argument type: %s' % argtype)
            self.arginLineEdit.setEnabled(argtype is not PyTango.DevVoid)
        elif item.type() == self.ATTR_ITEM:
            self.execBtn.hide()
            self.writeBtn.show()
            self.readBtn.show()
            name = self._getCurItemText()
            argtype = self._getAttrType(name)
            unit = self._attrs[name].unit
            self.argTypeLabel.setText('Attribute type: %s (unit: %s)' %
                                      (argtype, unit))
            can_w = self._attrs[name].writable in (PyTango.AttrWriteType.WRITE,
                                                   PyTango.AttrWriteType.READ_WRITE)
            can_r = self._attrs[name].writable in (PyTango.AttrWriteType.READ,
                                                   PyTango.AttrWriteType.READ_WITH_WRITE,
                                                   PyTango.AttrWriteType.READ_WRITE)
            self.readBtn.setVisible(can_r)
            self.writeBtn.setVisible(can_w)
            self.arginLineEdit.setEnabled(can_w)
            self.pollBtn.setEnabled(True)
        else:
            self.pollBtn.setEnabled(False)
            return
        if self.arginLineEdit.isEnabled():
            self.arginLineEdit.setFocus()
        self._genHelp()
        self.execBtn.setEnabled(True)

        self._updatePollButtonState()

    # -- INIT LIST WIDGET --

    def _fillListWidget(self):
        sep = QListWidgetItem('Commands')
        font = sep.font()
        font.setBold(True)
        sep.setFont(font)
        sep.setFlags(Qt.NoItemFlags)
        self.actionListWidget.addItem(sep)

        try:
            self._fillCmdList()
        except Exception:
            pass

        sep = QListWidgetItem('')
        sep.setFlags(Qt.NoItemFlags)
        self.actionListWidget.addItem(sep)

        sep = QListWidgetItem('Attributes')
        font = sep.font()
        font.setBold(True)
        sep.setFont(font)
        sep.setFlags(Qt.NoItemFlags)
        self.actionListWidget.addItem(sep)

        try:
            self._fillAttrList()
        except Exception:
            pass

    def _fillCmdList(self):
        self._cmds = {}

        for info in self.proxy.command_list_query():
            self._cmds[info.cmd_name] = info
            item = QListWidgetItem('  %s' % info.cmd_name,
                                   self.actionListWidget,
                                   self.CMD_ITEM)
            self.actionListWidget.addItem(item)
            if info.cmd_name in ('Communicate', 'BinaryCommunicate'):
                self.actionListWidget.setCurrentItem(item)

    def _fillAttrList(self):
        self._attrs = {}

        for info in sorted(self.proxy.attribute_list_query(),
                           key=lambda info: info.name):
            self._attrs[info.name] = info
            if info.name in ('State', 'Status'):
                continue
            item = QListWidgetItem('  %s' % info.name,
                                   self.actionListWidget,
                                   self.ATTR_ITEM)
            self.actionListWidget.addItem(item)
            if info.name.lower() == 'value':
                self.actionListWidget.setCurrentItem(item)

    # -- EXECUTION --

    def _execAction(self, with_control=False):
        item = self.actionListWidget.currentItem()
        if not item:
            return
        if item.type() == self.CMD_ITEM:
            self._execCmd(with_control)
        elif item.type() == self.ATTR_ITEM:
            if with_control:
                self._writeAttr()
            else:
                self._readAttr()

    def _readAttr(self):
        attr_name = self._getCurItemText()
        action = 'Read %s' % attr_name

        t1 = time.time()
        try:
            result = self.proxy.read_attribute(attr_name)
            t2 = time.time()
            val = to_presentation_multiline(self._getAttrType(attr_name),
                                            result.value, alt=True)
            args = ()
            if self._attrs[attr_name].writable != PyTango.AttrWriteType.READ \
               and not val.count('\n'):
                wval = to_presentation_multiline(self._getAttrType(attr_name),
                                                 result.w_value, alt=True)
                args = ('Last written', wval)
            self._logAction(action, val, t2 - t1, '%s::' % attr_name, *args)
        except Exception as err:
            t2 = time.time()
            self._logExc(action, err, t2 - t1, '%s::' % attr_name)

    def _writeAttr(self):
        attr = self._getCurItemText()
        intype = self._getAttrType(attr)

        try:
            argin = self._getArgin(intype)
        except Exception as err:
            QMessageBox.critical(self, 'Error', str(err))
            return

        strval = to_presentation_inline(intype, argin, alt=False)
        action = 'Write %s => %s' % (attr, strval)
        target = '%s:%s:%s' % (attr, int(intype), strval)

        t1 = time.time()
        try:
            self.proxy.write_attribute(attr, argin)
            t2 = time.time()
            self._logAction(action, 'successful', t2 - t1, target)
        except Exception as err:
            t2 = time.time()
            self._logExc(action, err, t2 - t1, target)

    def _execCmd(self, with_control=False):
        cmd = self._getCurItemText()

        if with_control and cmd == 'Communicate':
            cmd = 'WriteLine'

        cmdinfo = self._cmds[cmd]

        try:
            argin = self._getArgin(cmdinfo.in_type)
        except Exception as err:
            QMessageBox.critical(self, 'Error', str(err))
            return

        strval = to_presentation_inline(cmdinfo.in_type, argin, alt=False)
        action = '%s(%s)' % (cmd, strval)
        target = '%s:%s:%s' % (cmd, int(cmdinfo.in_type), strval)

        t1 = time.time()
        try:
            result = self.proxy.command_inout(cmd, argin)
            t2 = time.time()
            result = to_presentation_multiline(cmdinfo.out_type, result,
                                               alt=True)
            if not result:
                result = 'successful'
            self._logAction(action, result, t2 - t1, target)
        except Exception as err:
            t2 = time.time()
            self._logExc(action, err, t2 - t1, target)

    # -- OUTPUT LOGGING --

    def _logExc(self, action, exc, dt, target=None):
        action = escape_html(action)
        exc_text = escape_html(simpleExcDesc(exc))

        if target:
            action = '<a href="%s">%s</a>' % (target, action)

        self._log('[%5.1f ms] %s:<br/><span style="color:red">%s</span>' %
                  (1000 * dt, action, exc_text))

    def _logAction(self, action, result, dt, target,
                   add_text=None, add_result=None):
        action = escape_html(action)
        result = escape_html(result)

        if target:
            action = '<a href="%s">%s</a>' % (target, action)
        if add_text:
            result += '\n<span style="color:grey">%s: </span>%s' % (
                escape_html(add_text), escape_html(add_result))

        self._log('[%5.1f ms] %s:<br/>%s' % (1000 * dt, action, result))

    def _log(self, msg):
        # cleanup msg
        msg = msg.strip()
        # convert newlines
        msg = msg.replace('\n', '<br/>')
        # add date/time
        fmt = '<span style="font-weight:bold">%s:</span> %s'
        msg = fmt % (time.strftime('%d/%m %H:%M:%S'),
                     msg.replace('\n', '<br/>'))
        # Unicode conversion - assume latin1 for 8bit chars
        if isinstance(msg, bytes):
            msg = msg.decode('latin1')

        if self.outputTextBrowser.toPlainText():
            msg = self.outputTextBrowser.toHtml() + msg

        self.outputTextBrowser.setHtml(msg)
        self.outputTextBrowser.moveCursor(QTextCursor.End)

    # -- POLLING --

    def _startPoll(self):
        item = self.actionListWidget.currentItem()
        if not item:
            return
        name = self._getCurItemText()
        argtxt = ''
        if item.type() == self.CMD_ITEM:
            cmd = self._cmds[name]
            try:
                argin = self._getArgin(cmd.in_type)
            except Exception as err:
                QMessageBox.critical(self, 'Error', str(err))
                return
            if argin is not None:
                argtxt = '(' + to_presentation_inline(cmd.in_type, argin) + ')'

            def callback():
                res = self.proxy.command_inout(name, argin)
                return to_presentation_inline(cmd.out_type, res, alt=True)
        elif item.type() == self.ATTR_ITEM:
            attrtype = self._getAttrType(name)

            def callback():
                res = self.proxy.read_attribute(name).value
                return to_presentation_inline(attrtype, res, alt=True)
        interval = getPreferences()['pollinterval']
        widget = PollingWidget(self, name, argtxt, callback, interval)
        self._prefSrc.preferencesChanged.connect(widget.updatePreferences)
        layout = self.pollArea.widget().layout()
        layout.insertWidget(layout.count() - 1, widget)
        self.pollArea.show()
        self._updatePollButtonState()

    def _stopPoll(self, widget=None):
        if widget is None:
            widget = self._getPollWidget()

        layout = self.pollArea.widget().layout()
        layout.takeAt(layout.indexOf(widget)).widget().deleteLater()
        if layout.count() == 1:
            self.pollArea.hide()
        self._updatePollButtonState()

    def _updatePollButtonState(self):
        if self._isAlreadyPolled():
            self.pollBtn.setChecked(True)
        else:
            self.pollBtn.setChecked(False)

    # -- UTIL --

    def _getAttrType(self, name):
        attr = self._attrs[name]
        dtype = self._attrs[name].data_type
        if attr.data_format == PyTango.AttrDataFormat.SCALAR:
            return PyTango.CmdArgType.values[dtype]
        return PyTango.utils.scalar_to_array_type(dtype)

    def _getCurItemText(self):
        return str(self.actionListWidget.currentItem().text()).strip()

    def _getArgin(self, tgtype):
        argin = self.arginLineEdit.text().strip()
        return from_input_string(tgtype, argin)

    def _isAlreadyPolled(self, name=None):
        if name is None:
            name = self._getCurItemText()

        layout = self.pollArea.widget().layout()
        names = [str(layout.itemAt(i).widget().api)
                 for i in range(layout.count() - 1)]

        return name in names

    def _getPollWidget(self, name=None):
        if name is None:
            name = self._getCurItemText()

        layout = self.pollArea.widget().layout()
        widgets = [layout.itemAt(i).widget() for i in range(layout.count() - 1)]

        for entry in widgets:
            if entry.api == name:
                return entry
        return None


class PollingWidget(QWidget):

    def __init__(self, parent, api, arg, callback, pollinterval=1.0):
        QWidget.__init__(self, parent)
        loadUi(self, 'pollwidget.ui')

        self.api = api
        self.pollinterval = pollinterval
        self.mainwidget = parent
        self.callback = callback
        self.nameLabel.setText(api + arg)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.on_timer_timeout)
        self.on_timer_timeout()

    @pyqtSlot()
    def on_removeBtn_clicked(self):
        self.mainwidget._stopPoll(self)

    def on_timer_timeout(self):
        try:
            result = self.callback()
            self.valueLabel.setText(result)
            setForegroundColor(self.valueLabel,
                               self.palette().color(QPalette.WindowText))
        except Exception as err:
            self.valueLabel.setText(onelineExcDesc(err))
            setForegroundColor(self.valueLabel, QColor('red'))
        self.timer.start(self.pollinterval * 1000)

    def updatePreferences(self, prefs):
        self.pollinterval = prefs['pollinterval']


class PropertyWidget(QWidget):
    def __init__(self, parent, name, value):
        QWidget.__init__(self, parent)
        loadUi(self, 'propwidget.ui')
        self.propname = name
        self.nameLabel.setText(name)
        self.update(value)

    def update(self, value):
        self.origvalue = value
        self.valueLineEdit.setText(value)


class PropertyMissingWidget(QWidget):
    retry = pyqtSignal()

    def __init__(self, parent, exception):
        QWidget.__init__(self, parent)
        loadUi(self, 'propmissing.ui')

        if isinstance(exception, AttributeError):
            self.errorLbl.setText('GetProperties command is not present '
                                  'or device is not properly initialized')
        else:
            self.errorLbl.setText(str(exception))

        self.retryBtn.clicked.connect(self.retry)


class DevicePanel(QWidget):

    closeRequested = pyqtSignal(object)
    popoutRequested = pyqtSignal(object)

    def __init__(self, parent, devaddr, window=False):
        if window:
            QWidget.__init__(self, parent, Qt.Window)
        else:
            QWidget.__init__(self, parent)

        self.devaddr = devaddr
        self.proxy = None
        self._properties = {}
        self._propWidgets = []
        self._cmdAttrWidget = None
        self._guiCtrlWidget = None
        self._missingPropsWidget = None

        loadUi(self, 'device.ui')
        self.setWindowTitle(devaddr.compact)
        self.nameLbl.setText(devaddr.full)
        self.propWarnFrame.hide()

        if window:
            self.popOutBtn.hide()
            self.closeBtn.hide()
            self.layout().setContentsMargins(6, 6, 6, 6)
            for i in range(self.tabber.count()):
                self.tabber.widget(i).layout().setContentsMargins(0, 6, 0, 6)

        self.init()

    def init(self):
        self.ampelLbl.setPixmap(QPixmap(':/ampel-g.png'))
        self.applyPropsBtn.hide()
        self.refreshPropsBtn.hide()
        self.retryBtn.hide()
        self.tabber.setTabEnabled(0, True)
        self.tabber.setTabEnabled(1, True)
        self.tabber.setTabEnabled(2, True)

        db = PyTango.Database(self.devaddr.host, self.devaddr.port)
        try:
            db_info = db.get_device_info(self.devaddr.dev)
        except Exception as err:
            displayTangoError(err)
            self.ampelLbl.setPixmap(QPixmap(':/ampel-r.png'))
            self.retryBtn.show()
            self.tabber.setTabEnabled(0, False)
            self.tabber.setTabEnabled(1, False)
            self.tabber.setTabEnabled(2, False)
            self.tabber.setCurrentIndex(3)
        else:
            self._updateDbInfo(db_info)
            if not db_info.exported:
                self.ampelLbl.setPixmap(QPixmap(':/ampel-r.png'))
                self.retryBtn.show()

            if self.initDevice():
                self._updateDevInfo()
                self._updateCmdAttrTab()
                self._updatePropertyTab()
                self.tabber.setCurrentIndex(0)

                try:
                    desc = self.proxy.description()
                except PyTango.DevFailed:
                    desc = None

                if desc.lower() != 'a tango device':
                    self.descriptionLabel.setText(desc)
                else:
                    self.descriptionLabel.setHidden(True)
                    self.descriptionHeaderLabel.setHidden(True)
            else:
                self.tabber.setTabEnabled(0, False)
                self.tabber.setTabEnabled(1, False)
                self.tabber.setTabEnabled(2, False)
                self.tabber.setCurrentIndex(3)
                self.ampelLbl.setPixmap(QPixmap(':/ampel-r.png'))
                self.retryBtn.show()

    def closeEvent(self, event):
        # only called when the widget was popped out
        self.saveHistory()
        self.deleteLater()
        event.accept()

    def saveHistory(self):
        if self._cmdAttrWidget:
            self._cmdAttrWidget.saveHistory()

    def initDevice(self):
        try:
            self.proxy = PyTango.DeviceProxy(self.devaddr.full)
            self.proxy.ping()
        except Exception as err:
            displayTangoError(err)
            return False
        return True

    def _updateCmdAttrTab(self):
        self._cmdAttrWidget = GenericCmdAttrWidget(self.cmdTab, self.proxy,
                                                   self.devaddr.full)
        self.cmdTab.layout().addWidget(self._cmdAttrWidget)

    def _updatePropertyTab(self):
        if self._missingPropsWidget:
            self._missingPropsWidget.deleteLater()
        try:
            if not hasattr(self.proxy, 'GetProperties'):
                raise AttributeError
            try:
                properties = self.proxy.GetProperties()
            except Exception as err:
                displayTangoError(err)
                raise
            for i in range(len(properties) // 2):
                self._properties[properties[i*2]] = properties[i*2 + 1]

            for (name, value) in sorted(self._properties.items()):
                propwidget = PropertyWidget(self.propFrame, name, value)
                self.propFrame.layout().addWidget(propwidget)
                self._propWidgets.append(propwidget)
            self.propFrame.layout().addStretch(1)
            self.applyPropsBtn.show()
            self.refreshPropsBtn.show()
        except Exception as err:
            self._missingPropsWidget = PropertyMissingWidget(self, err)
            self._missingPropsWidget.retry.connect(self._updatePropertyTab)
            self.propFrame.layout().addWidget(self._missingPropsWidget)

    def _updateDbInfo(self, db_info):
        self.exportedLabel.setText(db_info.exported and 'yes' or 'no')
        self.startedLabel.setText(db_info.started_date)
        self.stoppedLabel.setText(db_info.stopped_date)
        self.devClassLabel.setText(db_info.class_name)
        self.serverIdLabel.setText(db_info.ds_full_name)

    def _updateDevInfo(self):
        try:
            info = self.proxy.info()
        except Exception:
            self.serverHostLabel.setText('(error querying running device information)')
            return
        self.serverHostLabel.setText(info.server_host)
        self.serverVersionLabel.setText(str(info.server_version))
        self.docUrlLabel.setText(info.doc_url.strip('Doc URL = '))

    def on_tabber_currentChanged(self, index):
        if index == 1 and self._guiCtrlWidget is None:
            self._setupGuiCtrl()

    @pyqtSlot()
    def on_applyPropsBtn_clicked(self):
        to_apply = []
        for widget in self._propWidgets:
            newvalue = str(widget.valueLineEdit.text())
            if newvalue != widget.origvalue:
                to_apply += [widget.propname, newvalue]

        if not to_apply:
            return

        try:
            self.proxy.SetProperties(to_apply)
        except Exception as err:
            displayTangoError(err)
            return

        self.propWarnFrame.show()
        self.on_refreshPropsBtn_clicked()
        if self._guiCtrlWidget:
            self._guiCtrlWidget.reinit()

    @pyqtSlot()
    def on_refreshPropsBtn_clicked(self):
        try:
            properties = self.proxy.GetProperties()
        except Exception as err:
            displayTangoError(err)
            return
        for i in range(len(properties) // 2):
            self._properties[properties[i*2]] = properties[i*2 + 1]
        for propwidget in self._propWidgets:
            propwidget.update(self._properties[propwidget.propname])

    @pyqtSlot()
    def on_popOutBtn_clicked(self):
        self.popoutRequested.emit(self.devaddr)

    @pyqtSlot()
    def on_closeBtn_clicked(self):
        self.closeRequested.emit(self.devaddr)

    @pyqtSlot()
    def on_retryBtn_clicked(self):
        self.init()

    def _setupGuiCtrl(self):
        # determine interface
        wid = self._cmdAttrWidget
        valuetype = None
        if 'value' in wid._attrs:
            typ = wid._getAttrType('value')
            valuetype = 'float' if typ \
                        in (PyTango.CmdArgType.DevFloat,
                            PyTango.CmdArgType.DevDouble) else 'int'
            valuetype += '-rw' if wid._attrs['value'].writable \
                         in (PyTango.AttrWriteType.WRITE,
                             PyTango.AttrWriteType.READ_WRITE) else '-ro'
        for (cls, cmds, attrs, need_valuetype) in INTERFACES:
            if all(cmd in wid._cmds for cmd in cmds) and \
               all(att in wid._attrs for att in attrs) and \
               valuetype == need_valuetype:
                try:
                    widget = cls(self, self.proxy, self._properties)
                except Exception as err:
                    widget = QLabel('An error occurred while setting up the '
                                    'GUI widget: %s.' % err, self)
                    widget.setAlignment(Qt.AlignCenter)
                break
        else:
            widget = QLabel('No MLZ compatible interface was found for this '
                            'device, or no GUI is available for this '
                            'interface.', self)
            widget.setAlignment(Qt.AlignCenter)
        self.guiTab.layout().addWidget(widget)
        self._guiCtrlWidget = widget
