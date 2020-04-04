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
#   Georg Brandl <georg.brandl@frm2.tum.de>
#
# *****************************************************************************

import os
import socket
from os import path

from quango.qt import QApplication, QMessageBox, QPalette, uic

import psutil
import PyTango

try:
    import ipaddress
except ImportError:
    import ipaddr as ipaddress


uipath = path.dirname(__file__)


def determineSubnet():
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        # no hostname set, or weird hosts configuration
        return None
    ifs = psutil.net_if_addrs()

    for _, addrs in ifs.items():
        for addr in addrs:
            if addr.address == ip:
                return str(ipaddress.ip_network(u'%s/%s' %
                                                (ip, addr.netmask), False))
    return None


def getSubnetHostsAddrs(subnet):
    net = ipaddress.IPv4Network(str(subnet))

    # ipaddr compatiblity
    if hasattr(net, 'iterhosts'):
        net.hosts = net.iterhosts

    return [str(entry) for entry in net.hosts()]


def loadUi(widget, uiname, subdir='ui'):
    uic.loadUi(path.join(uipath, subdir, uiname), widget)


class TangoAddress(object):
    """Represents either a Tango database or device address."""
    @staticmethod
    def from_host(addr):
        if not addr:
            addr = os.getenv('TANGO_HOST') or 'localhost:10000'
        if addr.startswith('tango://'):
            addr = addr[8:]
        if ':' in addr:
            port = addr.rsplit(':')[-1]
            host = addr[:-len(port)-1]
        else:
            port = '10000'
            host = addr
        host = socket.getfqdn(host)
        return TangoAddress(host, port)

    @staticmethod
    def from_string(addr, default_db=None):
        if default_db is None:
            default_db = os.getenv('TANGO_HOST') or 'localhost:10000'
        if addr.startswith('tango://'):
            addr = addr[8:]
        if addr.count('/') == 3:
            db, dev = addr.split('/', 1)
        else:
            db, dev = default_db, addr
        domain, family, member = dev.split('/')
        return TangoAddress.from_host(db).with_(domain=domain, family=family,
                                                member=member)

    def __init__(self, host, port, domain='', family='', member=''):
        self.host = str(host)
        self.port = str(port)
        self.domain = str(domain)
        self.family = str(family)
        self.member = str(member)

    def __lt__(self, other):
        return self.full < other.full

    def with_(self, **props):
        newaddr = TangoAddress(self.host, self.port,
                               self.domain, self.family, self.member)
        for key, value in props.items():
            setattr(newaddr, key, str(value))
        return newaddr

    def with_dev(self, dev):
        return TangoAddress.from_string(dev, default_db=self.db)

    @property
    def full(self):
        res = 'tango://%s:%s' % (self.host, self.port)
        if self.domain:
            res += '/' + self.domain
            if self.family:
                res += '/' + self.family
                if self.member:
                    res += '/' + self.member
        return res

    @property
    def compact(self):
        res = '//%s' % self.host
        if self.domain:
            res += '/' + self.domain
            if self.family:
                res += '/' + self.family
                if self.member:
                    res += '/' + self.member
        return res

    @property
    def db(self):
        return '%s:%s' % (self.host, self.port)

    @property
    def dev(self):
        return '%s/%s/%s' % (self.domain, self.family, self.member)

    def __hash__(self):
        return hash(self.host + self.port + self.domain +
                    self.family + self.member)

    def __eq__(self, other):
        return self.host == other.host and \
            self.port == other.port and \
            self.domain == other.domain and \
            self.family == other.family and \
            self.member == other.member


def parseTangoError(exc):
    if isinstance(exc, PyTango.DevFailed):
        err = exc.args[0]
        return {
            'reason': err.reason,
            'desc': err.desc,
            'origin': err.origin,
            'level': err.severity
        }
    return {
        'reason': exc.__class__.__name__,
        'desc': str(exc),
        'origin': '',
        'level': PyTango.ErrSeverity.ERR,
    }


def displayTangoError(err, interactive=True, context=None):
    if interactive:
        tangoErrorBox(err, context)
    else:
        tangoErrorBar(err, context)


def tangoErrorBar(err, context=None):
    parsed = parseTangoError(err)
    statusbar = getStatusBar()

    msg = '%s - %s' % (parsed['reason'], parsed['desc'])
    if context:
        msg = '%s: %s' % (context, msg)

    statusbar.showMessage(msg)


def tangoErrorBox(err, context=None):
    parsed = parseTangoError(err)

    boxes = {
        PyTango.ErrSeverity.WARN: QMessageBox.warning,
    }
    boxfunc = boxes.get(parsed['level'], QMessageBox.critical)

    title = 'TANGO ERROR: %s: %s' % (parsed['origin'], parsed['reason'])

    context_str = ''
    if context:
        context_str = '''
        <h5>Context</h5>
        <p style="margin-top:0px; margin-left:20px;">%s</p>
        ''' % context

    msg = '''
    <h3>TANGO ERROR</h3>
    %s
    <h5>Reason</h5>
    <p style="margin-top:0px; margin-left:20px;">%s</p>
    <h5>Description</h5>
    <p style="margin-top:0px; margin-left:20px;">%s</p>
    <h5>Origin</h5>
    <p style="margin-top:0px; margin-left:20px;">%s</p>
    <h5>Details</h5>
    <p style="margin-top:0px; margin-left:20px;"><pre>%s</pre></p>
    ''' % (
        context_str,
        parsed['reason'],
        parsed['desc'],
        parsed['origin'],
        str(err)
        # traceback.format_exc()
    )

    boxfunc(None, title, msg)


def onelineExcDesc(exc):
    """Return a *simple* one-line exception string from a convoluted PyTango exc.

    Takes the first line of the exception's string representation that looks
    like it could be the topmost "description" of the exception.
    """
    lines = str(exc).splitlines()
    firstline = ''
    desc = ''
    errtype = exc.__class__.__name__
    for line in lines:
        line = line.strip()
        if line.endswith(('DevError[', 'DevFailed[')):
            continue
        if not firstline:
            firstline = line
        if line.startswith('desc ='):
            desc = line[6:].strip()
        if line.startswith('origin =') and desc:
            desc += ' (in %s)' % line[8:].strip()
        if line.startswith('reason =') and desc:
            desc = '%s: %s' % (line[8:].strip(), desc)
            break
    if desc:
        return errtype + ': ' + desc
    return errtype + ': ' + firstline


def simpleExcDesc(exc):
    """Return a *simple* multi-line exception string from a convoluted PyTango exc.

    Takes the first line of the exception's string representation that looks
    like it could be the topmost "description" of the exception.
    """
    lines = str(exc).splitlines()
    firstline = ''
    desc = ''
    origin = ''
    reason = ''
    errtype = exc.__class__.__name__
    for line in lines:
        line = line.strip()
        if line.endswith(('DevError[', 'DevFailed[')):
            continue
        if not firstline:
            firstline = line
        if line.startswith('desc ='):
            desc = line[6:].strip()
        if line.startswith('origin =') and desc:
            origin = line[8:].strip()
        if line.startswith('reason =') and desc:
            reason = line[8:].strip()
            break
    if desc:
        ret = '%s:\n  reason = %s\n  desc = %s' % (errtype, reason, desc)
        if origin:
            ret += '\n  origin = %s' % origin
        return ret
    return errtype + ':\n  ' + firstline


def setForegroundColor(widget, color):
    palette = widget.palette()
    palette.setColor(QPalette.WindowText, color)
    palette.setColor(QPalette.Text, color)
    widget.setForegroundRole(QPalette.WindowText)
    widget.setPalette(palette)


def getPreferences():
    for entry in QApplication.instance().topLevelWidgets():
        if hasattr(entry, 'prefs'):
            return entry.prefs
    return None


def getStatusBar():
    for entry in QApplication.instance().topLevelWidgets():
        if hasattr(entry, 'statusBar'):
            return entry.statusBar()
    return None
