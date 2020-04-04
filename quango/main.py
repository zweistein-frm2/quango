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

import optparse
import os
import sys

# Don't move this below the PyTango import!
from quango.qt import QApplication, QBrush, QByteArray, QColor, QDialog, \
    QHBoxLayout, QIcon, QInputDialog, QLabel, QMainWindow, QMenu, \
    QMessageBox, QPixmap, QRegExp, QSettings, Qt, QTreeWidgetItem, \
    QTreeWidgetItemIterator, QWidget, pyqtSignal, pyqtSlot

# pylint: disable=wrong-import-order
import PyTango
from six import reraise

from quango.device import DevicePanel
from quango.pyshell import ConsoleWindow
from quango.subnet import SubnetInputDialog, SubnetScanner
from quango.utils import TangoAddress, displayTangoError, loadUi
from quango.version import get_version

DEV_TYPE = 1
HOST_TYPE = 2
FAMILY_TYPE = 3
DEV_ADDR = 32
HOST_ADDR = 33

SPECIAL_DOMAINS = [
    'dserver',
    'sys',
    'tango'
]


class OpenDevListWidgetEntry(QWidget):

    closeRequested = pyqtSignal(object)

    def __init__(self, parent, devaddr, item):
        QWidget.__init__(self, parent)
        loadUi(self, 'opendevslistentry.ui')

        self.item = item
        self.addrLabel.setText(devaddr.compact)

    @pyqtSlot()
    def on_closePushButton_clicked(self):
        self.closeRequested.emit(self.item.data(DEV_ADDR))


class PreferencesDialog(QDialog):
    def __init__(self, parent, prefsDict):
        QDialog.__init__(self, parent)
        loadUi(self, 'preferences.ui')

        self.setPrefsDict(prefsDict)

    def setPrefsDict(self, prefs_dict):
        self.pollIntervalBox.setValue(prefs_dict.get('pollinterval', 1))
        self.specialDomainBox.setChecked(
            prefs_dict.get('displayspecialdomains', False))

    def getPrefsDict(self):
        return {
            'pollinterval': self.pollIntervalBox.value(),
            'displayspecialdomains': self.specialDomainBox.isChecked(),
        }


class MainWindow(QMainWindow):

    preferencesChanged = pyqtSignal(dict)

    def __init__(self):
        QMainWindow.__init__(self)

        loadUi(self, 'main.ui')
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.placeholderLabel = QLabel(self)
        self.placeholderLabel.setPixmap(QPixmap(':/appicon_large.png'))
        self.placeholderLabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.placeholderLabel)
        self.frame.setLayout(layout)
        self.openDevsList.hide()
        self.treeSplitter.setStretchFactor(0, 20)
        self.treeSplitter.setStretchFactor(1, 5)

        self.statusBar().showMessage('Enno says: "Quak"!', 800)
        self._pyshell = None

        settings = QSettings()
        self.splitter.restoreState(settings.value('split', '', QByteArray))
        self.tree.header().restoreState(settings.value('header', '', QByteArray))
        self.restoreGeometry(settings.value('geometry', '', QByteArray))

        self._treeItems = {}
        self._tangoHosts = []
        self._devPanels = {}
        self.prefs = settings.value('prefs', {
            'pollinterval': 1,
            'displayspecialdomains': False,
        })

        for host in settings.value('last_hosts') or []:
            self.addTangoHost(TangoAddress.from_host(host), root_only=True,
                              expanded=True)

        self._lastOpen = settings.value('open_devices') or []

        self._subnetScanner = SubnetScanner()
        self._subnetScanner.hostFound.connect(self.addTangoHost)
        self._subnetScanner.scanNotify.connect(self.statusBar().showMessage)
        self._subnetScanner.finished.connect(self.subnetScanFinished)

    def closeEvent(self, event):
        open_devs = []
        for (addr, panel) in self._devPanels.items():
            panel.saveHistory()
            open_devs.append(addr.full)
        self._devPanels.clear()
        settings = QSettings()
        settings.setValue('split', self.splitter.saveState())
        settings.setValue('header', self.tree.header().saveState())
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('last_hosts', [addr.db for addr in self._tangoHosts])
        settings.setValue('prefs', self.prefs)
        settings.setValue('open_devices', open_devs)
        return QMainWindow.closeEvent(self, event)

    @pyqtSlot()
    def on_actionReopen_triggered(self):
        for dev in self._lastOpen:
            self.openDevice(TangoAddress.from_string(dev))

    @pyqtSlot()
    def on_actionScan_subnet_triggered(self):
        dlg = SubnetInputDialog(self)
        if dlg.exec_():
            self._subnetScanner.setSubnet(dlg.subnet)
            self.actionScan_subnet.setEnabled(False)
            self._subnetScanner.start()

    @pyqtSlot()
    def on_actionClear_hosts_triggered(self):
        self.tree.clear()
        self._tangoHosts = []
        self._treeItems = {}

    def subnetScanFinished(self):
        self.statusBar().showMessage('Subnet scan finished')
        self.actionScan_subnet.setEnabled(True)

    @pyqtSlot()
    def on_actionQuit_triggered(self):
        self.close()

    @pyqtSlot()
    def on_actionPython_shell_triggered(self):
        if self._pyshell:
            if self._pyshell.isVisible():
                self._pyshell.raise_()
                return
            else:
                self._pyshell.deleteLater()
                self._pyshell = None

        open_devs = self._getOpenDevs()
        ns = {
            'devs': {
                devaddr.full: PyTango.DeviceProxy(devaddr.full)
                for devaddr in open_devs
            }
        }
        cur_dev = self._getCurrentlyOpenDev()
        ns['dev'] = PyTango.DeviceProxy(cur_dev.full) if cur_dev else None

        banner = '''
    Quango device shell

                    :mm+
                    sNNN.
                    -mNd`
                     .o+-
                    +NNNNy`
                   `mNNyoh/
               .-:/oNNh+///.`
            .:+++++oNN+++++++/-`
          `/++++/:--ms`..-/++++/-
         ./+++/.    y:     `-++++:
        .++++:      /.       ./+++:
        :+++/                 .++++.
       `/+++-                  ++++-
       `/+++-            .-`   ++++-
        :+++/`   -+`      `+yo+++++`
        ./+++/./ho          `sNNds-
       oh`/+shNm/         `-/++hNNm/
      .NNNmNNNh+++/:---::/+++++/sNNNs
      `yNNNd+-:+++++++++++++/:/odNNN+/oo/`
    -ydy`.`     .--:://::-.`   `-/:` yNNNNo
   +NNNy                              -oyyo
   yNd+

    devs: Dictonary of open devices {address : proxy}
    dev: currently open device (proxy)
        '''

        self._pyshell = ConsoleWindow('Quango device shell', ns, banner)
        self._pyshell.resize(900, 600)
        self._pyshell.show()

    @pyqtSlot()
    def on_actionAbout_triggered(self):
        QMessageBox.about(
            self, 'About Quango',
            '''
            <h2>About Quango</h2>
            <p style="font-style: italic">
              (C) 2015-2017 MLZ instrument control
            </p>
            <p>
              Quango is a generic Tango device client.
            </p>
            <h3>Authors:</h3>
            <ul>
              <li>Copyright (C) 2015-2019
                <a href="mailto:g.brandl@fz-juelich.de">Georg Brandl</a></li>
              <li>Copyright (C) 2015-2017
                <a href="mailto:alexander.lenz@frm2.tum.de">Alexander Lenz</a></li>
            </ul>
            <p>
              Quango is published under the
              <a href="http://www.gnu.org/licenses/gpl.html">GPL
                (GNU General Public License)</a>
            </p>
            <p style="font-weight: bold">
              Version: %s
            </p>
            ''' % get_version())

    @pyqtSlot()
    def on_actionAdd_Tango_host_triggered(self):
        host, accepted = QInputDialog.getText(self, 'Add tango host',
                                              'New tango host:')
        if accepted:
            try:
                self.addTangoHost(TangoAddress.from_host(host),
                                  onsuccess_only=True, expanded=True)
            except Exception as err:
                displayTangoError(err)

    @pyqtSlot()
    def on_actionUpdate_device_list_triggered(self):
        for host in list(self._tangoHosts):
            if self._treeItems[host].childCount() > 0:
                self.addTangoHost(host, expanded=True)
        # remove current dev panel from display
        previous = self.frame.layout().takeAt(0)
        if previous:
            previous.widget().hide()

    @pyqtSlot()
    def on_actionPreferences_triggered(self):
        dlg = PreferencesDialog(self, self.prefs)
        if dlg.exec_():
            self.prefs = dlg.getPrefsDict()
            self.preferencesChanged.emit(self.prefs)

            self._updateSpecialDomainsVisible(self.prefs['displayspecialdomains'])

        self._updateSpecialDomainsVisible(self.prefs['displayspecialdomains'])

    def on_tree_customContextMenuRequested(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return

        # top level => tango host
        if not item.parent():
            self._showHostContextMenu(pos, item)
        # DEV_TYPE => device item
        elif item.type() == DEV_TYPE:
            self._showDeviceContextMenu(pos, item)

    def on_tree_itemClicked(self, item, _col):
        if item.type() != DEV_TYPE:
            self.actionPop_out.setEnabled(False)
            return
        self.actionPop_out.setEnabled(True)

        devaddr = item.data(0, DEV_ADDR)
        self.openDevice(devaddr)

    def on_tree_itemExpanded(self, item):
        if item.type() == HOST_TYPE and item.childCount() == 0:
            try:
                self.addTangoHost(item.data(0, HOST_ADDR), expanded=True)
            except Exception as err:
                item.setExpanded(False)
                displayTangoError(err)

    def on_openDevsList_itemClicked(self, item):
        devaddr = item.data(DEV_ADDR)
        self.openDevice(devaddr)

    def on_filterLineEdit_textChanged(self, text):
        rx = QRegExp(text)
        it = QTreeWidgetItemIterator(self.tree,
                                     QTreeWidgetItemIterator.NoChildren)
        while it.value():
            item = it.value()
            if item.type() == DEV_TYPE:
                item.setHidden(rx.indexIn(item.text(0)) == -1)
            it += 1
        it = QTreeWidgetItemIterator(self.tree, QTreeWidgetItemIterator.All)
        while it.value():
            item = it.value()
            if item.type() == FAMILY_TYPE:
                item.setHidden(not any(not item.child(i).isHidden()
                                       for i in range(item.childCount())))
            it += 1

    @pyqtSlot()
    def on_refreshListBtn_clicked(self):
        self.on_actionUpdate_device_list_triggered()

    @pyqtSlot(QWidget, QWidget)
    def raiseWindows(self, old, new):
        if new is not None and old is None:
            app = QApplication.instance()
            windows = app.topLevelWidgets()

            for window in windows:
                window.raise_()
            new.raise_()

    @pyqtSlot(object)
    def closeDevice(self, devaddr):
        if devaddr in self._devPanels:
            self._devPanels[devaddr].hide()
            panel = self._devPanels.pop(devaddr)
            if self.frame.layout().itemAt(0).widget() is panel:
                self.frame.layout().takeAt(0)
            panel.saveHistory()
            panel.deleteLater()

        index, _ = self._findOpenDevListEntry(devaddr)
        self.openDevsList.takeItem(index)

        if self.openDevsList.count() == 0:
            self.openDevsList.hide()
            self.frame.layout().addWidget(self.placeholderLabel)
            self.placeholderLabel.show()
        else:
            next_item = self.openDevsList.currentItem()
            addr = next_item.data(DEV_ADDR)
            if addr in self._devPanels:
                self.openDevice(addr)

    @pyqtSlot(object)
    def popoutDevice(self, devaddr):
        self.openDevice(devaddr, True)
        self.closeDevice(devaddr)

    def addTangoHost(self, hostaddr, root_only=False, onsuccess_only=False,
                     expanded=False):
        def add_or_retrieve(addr, parent, itype, texts, icon):
            if addr in self._treeItems:
                return self._treeItems[addr]
            item = QTreeWidgetItem(texts, itype)
            item.setIcon(0, QIcon(icon))
            if parent:
                parent.addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            self.tree.sortItems(0, Qt.AscendingOrder)
            self._treeItems[addr] = item
            return item

        hostitem = None
        exc_info = None
        if not root_only:
            try:
                db = PyTango.Database(hostaddr.host, hostaddr.port)
            except Exception:
                exc_info = sys.exc_info()

        if not exc_info or not onsuccess_only or root_only:
            hostitem = add_or_retrieve(hostaddr, None, HOST_TYPE,
                                       [hostaddr.host, ''],
                                       ':/server.png')
            # always show expand indicator
            hostitem.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            hostitem.setData(0, HOST_ADDR, hostaddr)

        if exc_info:
            reraise(*exc_info)

        if hostaddr not in self._tangoHosts:
            self._tangoHosts.append(hostaddr)

        if root_only or not hostitem:
            return

        hostitem.setExpanded(expanded)

        needed_nodes = set([hostaddr])

        hostinfo = {}
        devices = {}

        # get a list of all devices
        for server in db.get_server_list():
            hostinfo[server] = {}
            devclslist = db.get_device_class_list(server)
            for i in range(0, len(devclslist), 2):
                devname, devcls = devclslist[i:i + 2]
                devinfo = db.get_device_info(devname)
                hostinfo[devname] = [server, devcls, devinfo]

                domain, family, member = devname.split('/')
                devices.setdefault(domain, {}).setdefault(family, set()).add(member)

        # create tree widget items for the devices
        for domain in sorted(devices):
            domaddr = hostaddr.with_(domain=domain)
            needed_nodes.add(domaddr)
            domainitem = add_or_retrieve(domaddr, hostitem, 0, [domain, ''],
                                         ':/folder.png')
            if domain not in ('sys', 'dserver', 'tango'):
                domainitem.setExpanded(True)
            for family in sorted(devices[domain]):
                famaddr = domaddr.with_(family=family)
                needed_nodes.add(famaddr)
                familyitem = add_or_retrieve(famaddr, domainitem, FAMILY_TYPE,
                                             [family, ''], ':/folder.png')
                for member in sorted(devices[domain][family]):
                    devaddr = famaddr.with_(member=member)
                    needed_nodes.add(devaddr)
                    devitem = add_or_retrieve(devaddr, familyitem, DEV_TYPE,
                                              [member, hostinfo[devaddr.dev][0]],
                                              ':/plug.png')
                    devitem.setData(0, DEV_ADDR, devaddr)
                    if hostinfo[devaddr.dev][2].exported:
                        devitem.setIcon(0, QIcon(':/plug.png'))
                        devitem.setForeground(0, QBrush(QColor('black')))
                    else:
                        devitem.setIcon(0, QIcon(':/plug-disconnect.png'))
                        devitem.setForeground(0, QBrush(QColor('#666666')))

        # remove nodes for devices/groups that don't exist anymore
        for nodeaddr in sorted(self._treeItems, reverse=True):
            if nodeaddr.db == hostaddr.db:
                if nodeaddr not in needed_nodes:
                    item = self._treeItems.pop(nodeaddr)
                    item.parent().takeChild(item.parent().indexOfChild(item))

        self.tree.sortItems(0, Qt.AscendingOrder)
        self._updateSpecialDomainsVisible()

    def openDevice(self, devaddr, pop_out=False):
        if pop_out:
            panel = DevicePanel(self, devaddr, window=True)
            panel.show()
        else:
            if devaddr in self._treeItems:
                self.tree.setCurrentItem(self._treeItems[devaddr])
                self.tree.scrollToItem(self._treeItems[devaddr])
            if devaddr not in self._devPanels:
                panel = self._devPanels[devaddr] = DevicePanel(self, devaddr)
                panel.popoutRequested.connect(self.popoutDevice)
                panel.closeRequested.connect(self.closeDevice)
                self._addOpenDevListEntry(devaddr)
            else:
                panel = self._devPanels[devaddr]
            self.setWindowTitle('Quango: ' + devaddr.compact)
            previous = self.frame.layout().takeAt(0)
            if previous:
                previous.widget().hide()
            self.frame.layout().addWidget(panel)
            panel.show()

            index, _ = self._findOpenDevListEntry(devaddr)
            self.openDevsList.setCurrentRow(index)

    def _displayDbInfo(self, addr):
        try:
            db = PyTango.Database(addr.host, addr.port)
        except Exception as err:
            displayTangoError(err)
        else:
            QMessageBox.information(self, addr.db, db.get_info())

    def _showHostContextMenu(self, pos, item):
        menu = QMenu()
        info_action = menu.addAction('Info')
        info_action.setIcon(QIcon(':/information.png'))

        remove_action = menu.addAction('Remove')
        remove_action.setIcon(QIcon(':/cross.png'))

        chosen_action = menu.exec_(self.tree.viewport().mapToGlobal(pos))

        if chosen_action == info_action:
            self._displayDbInfo(item.data(0, HOST_ADDR))
        elif chosen_action == remove_action:
            self._tangoHosts.remove(item.data(0, HOST_ADDR))
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))

    def _showDeviceContextMenu(self, pos, item):
        devaddr = item.data(0, DEV_ADDR)

        menu = QMenu()
        popout_action = menu.addAction('Pop out')
        popout_action.setIcon(QIcon(':/applications-blue.png'))
        menu.addSeparator()
        delete_action = menu.addAction('Delete device')
        delete_action.setIcon(QIcon(':/cross-shield.png'))
        delete_server_action = menu.addAction('Delete entire server')
        delete_server_action.setIcon(QIcon(':/cross-shield-black.png'))

        chosen_action = menu.exec_(self.tree.viewport().mapToGlobal(pos))

        if chosen_action == popout_action:
            self.openDevice(devaddr, True)
        elif chosen_action == delete_action:
            db = PyTango.Database(devaddr.host, devaddr.port)
            info = db.get_device_info(devaddr.dev)
            msg = 'This device is currently exported! Are you sure?' \
                if info.exported else 'Are you sure?'
            if QMessageBox.question(self, 'Delete device', msg,
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.No:
                return
            db.delete_device(devaddr.dev)
            self.on_actionUpdate_device_list_triggered()
        elif chosen_action == delete_server_action:
            db = PyTango.Database(devaddr.host, devaddr.port)
            info = db.get_device_info(devaddr.dev)
            msg = 'This device is currently exported! Are you sure?' \
                if info.exported else 'Are you sure?'
            if QMessageBox.question(self, 'Delete entire server', msg,
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.No:
                return
            db.delete_server(info.ds_full_name)
            self.on_actionUpdate_device_list_triggered()

    def _addOpenDevListEntry(self, devaddr):
        self.openDevsList.addItem('')
        item = self.openDevsList.item(
            self.openDevsList.count() - 1
        )

        item.setData(DEV_ADDR, devaddr)
        widget = OpenDevListWidgetEntry(self.openDevsList,
                                        devaddr, item)
        widget.closeRequested.connect(self.closeDevice)

        self.openDevsList.setItemWidget(
            item, widget
        )

        self.openDevsList.show()

    def _findOpenDevListEntry(self, devaddr):
        for i in range(self.openDevsList.count()):
            item = self.openDevsList.item(i)
            if devaddr == item.data(DEV_ADDR):
                return (i, item)
        return None

    def _getOpenDevs(self):
        result = []
        for i in range(self.openDevsList.count()):
            item = self.openDevsList.item(i)
            result.append(item.data(DEV_ADDR))

        return result

    def _getCurrentlyOpenDev(self):
        item = self.openDevsList.currentItem()

        if not item:
            return None
        return item.data(DEV_ADDR)

    def _updateSpecialDomainsVisible(self, value=None):
        if value is None:
            value = self.prefs['displayspecialdomains']

        for name, item in self._treeItems.items():
            if name.domain in SPECIAL_DOMAINS:
                item.setHidden(not value)


def main():
    if [int(x) for x in PyTango.__version__.split('.')[:3]] < [8, 1, 0]:
        raise RuntimeError('Quango needs at least PyTango version 8.1.0 to run')

    parser = optparse.OptionParser(usage='%prog [options] DEVICE ...')
    parser.add_option('-n',
                      '--tango-host',
                      action='append',
                      default=[],
                      help='Tango host')

    opts, args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    app.setOrganizationName('mlz')
    app.setApplicationName('quango')
    window = MainWindow()

    app.focusChanged.connect(lambda *args: window.raiseWindows)

    if not opts.tango_host:
        opts.tango_host.append(os.getenv('TANGO_HOST'))

    for entry in opts.tango_host:
        try:
            window.addTangoHost(TangoAddress.from_host(entry),
                                onsuccess_only=True)
        except Exception as err:
            # display errors just if tango-host has been explicitly set
            if entry:
                displayTangoError(err)

    if args:
        if len(opts.tango_host) == 1:
            dbaddr = TangoAddress.from_host(opts.tango_host[0])
            devices = [dbaddr.with_dev(dev) for dev in args]
        else:
            devices = [TangoAddress.from_string(dev) for dev in args]
        window.openDevice(devices[0])
        for entry in devices[1:]:
            window.openDevice(entry, True)

    window.show()
    app.exec_()

    return 0
