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

from quango.qt import  QApplication,QFileDialog, QInputDialog, QLabel, QMessageBox, Qt, \
    QTimer,QImage,QPoint, QPainter,QPen,QBrush,QTextCharFormat,QWidget, pyqtSignal,pyqtSlot

from PyTango import CmdArgType, DevState
from six import text_type

from quango.utils import getPreferences, loadUi, simpleExcDesc
from quango.value import from_input_string, to_presentation_inline

import copy
import re
import cv2 as cv
import numpy as np

def loud_float(x):
    try:
        return float(x)
    except ValueError:
        QMessageBox.warning(None, 'Error', 'Please enter a valid number.')
        raise


def loud_int(x):
    try:
        return int(x)
    except ValueError:
        QMessageBox.warning(None, 'Error', 'Please enter a valid integer.')
        raise


def clamp(val, mini, maxi):
    return mini if val < mini else maxi if val > maxi else val


class SqueezedLabel(QLabel):
    """A label that elides text to fit its width."""

    def __init__(self, *args):
        self._fulltext = ''
        QLabel.__init__(self, *args)
        self._squeeze()

    def resizeEvent(self, event):
        self._squeeze()
        QLabel.resizeEvent(self, event)

    def setText(self, text):
        self._fulltext = text
        self._squeeze(text)

    def minimumSizeHint(self):
        sh = QLabel.minimumSizeHint(self)
        sh.setWidth(-1)
        return sh

    def _squeeze(self, text=None):
        if text is None:
            text = self._fulltext or self.text()
        fm = self.fontMetrics()
        labelwidth = self.size().width()
        squeezed = False
        new_lines = []
        for line in text.split('\n'):
            if fm.width(line) > labelwidth:
                squeezed = True
                new_lines.append(fm.elidedText(line, Qt.ElideRight, labelwidth))
            else:
                new_lines.append(line)
        if squeezed:
            QLabel.setText(self, '\n'.join(map(text_type, new_lines)))
            self.setToolTip(self._fulltext)
        else:
            QLabel.setText(self, self._fulltext)
            self.setToolTip('')


class Base(QWidget):
    POLL_ATTRS = []

    pollData = pyqtSignal(object)

    def __init__(self, parent, proxy, props):
        QWidget.__init__(self, parent)
        self.proxy = proxy
        self.props = props
        self._poll_interval = getPreferences()['pollinterval']
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.on_timer_timeout)
        self.pollData.connect(self.on_pollData)
        loadUi(self, self.UIFILE)
        self.pollErr.hide()
        self.reinit()
        self._triggerPoll()

        for entry in QApplication.instance().topLevelWidgets():
            if hasattr(entry, 'preferencesChanged'):
                entry.preferencesChanged.connect(self.updatePrefs)
                break

    def reinit(self):
        pass

    def updatePrefs(self, prefs):
        self._poll_interval = prefs['pollinterval']

    def on_pollData(self, attrs):
        pass

    def _execute(self, cmd, arg=None):
        self.errorLbl.setText('none')
        try:
            res = self.proxy.command_inout(cmd, arg)
        except Exception as err:
            self.errorLbl.setText(simpleExcDesc(err))
            res = None
        self._triggerPoll()
        return res

    def _write_attr(self, attr, val):
        self.errorLbl.setText('none')
        try:
            self.proxy.write_attribute(attr, val)
        except Exception as err:
            self.errorLbl.setText(simpleExcDesc(err))
        self._triggerPoll()

    def _triggerPoll(self):
        self._timer.stop()
        self._timer.timeout.emit()

    def on_timer_timeout(self):
        attrs = {}
        try:
            state = self.proxy.State()
            status = self.proxy.Status()
        except Exception:
            self._setStatus(DevState.UNKNOWN, '???', '???')
            self.pollErr.show()
        else:
            if status:
                attrs['status'] = '%s: %s' % (state, status)
            else:
                attrs['status'] = str(state)
            self._setStatus(state, status, attrs['status'])
            try:
                for attr in self.POLL_ATTRS:
                    attrs[attr] = self.proxy.read_attribute(attr)
            except Exception:
                self.pollErr.show()
            else:
                self.pollErr.hide()
                self.pollData.emit(attrs)
        self._timer.start(self._poll_interval * 1000)

    def _setStatus(self, state, _status, text):
        label = self.statusLbl
        label.setText(text)
        if state == DevState.ON:
            label.setStyleSheet('color: #009900')
        elif state == DevState.MOVING:
            label.setStyleSheet('background-color: yellow')
        elif state == DevState.ALARM:
            label.setStyleSheet('background-color: #ffa500')
        elif state == DevState.FAULT:
            label.setStyleSheet('color: white; background-color: #cc0000')
        elif state == DevState.OFF:
            label.setStyleSheet('color: white; background-color: #666666')
        else:
            label.setStyleSheet('')

    @pyqtSlot()
    def on_resetBtn_clicked(self):
        self._execute('Reset')

    @pyqtSlot()
    def on_onBtn_clicked(self):
        self._execute('On')

    @pyqtSlot()
    def on_offBtn_clicked(self):
        self._execute('Off')


class StringIO(Base):
    UIFILE = 'mlz_stringio.ui'
    POLL_ATTRS = []

    def reinit(self):
        self._polled = [False] * 4
        for n in range(1, 5):
            def do_comm(_ignored=None, n=n):
                txt = getattr(self, 'comEdit%d' % n).text()
                inp = from_input_string(CmdArgType.DevString, txt)
                outp = self._execute('Communicate', inp)
                res = to_presentation_inline(CmdArgType.DevString, outp)
                getattr(self, 'comRes%d' % n).setText(res)
            getattr(self, 'comEdit%d' % n).returnPressed.connect(do_comm)
            getattr(self, 'comBtn%d' % n).clicked.connect(do_comm)

            def do_poll(active, n=n):
                self._polled[n - 1] = active
                getattr(self, 'comBtn%d' % n).setEnabled(not active)
            getattr(self, 'pollBtn%d' % n).toggled.connect(do_poll)

            def do_write(_ignored=None, n=n):
                txt = getattr(self, 'writeEdit%d' % n).text()
                inp = from_input_string(CmdArgType.DevString, txt)
                self._execute('WriteLine', inp)
            getattr(self, 'writeEdit%d' % n).returnPressed.connect(do_write)
            getattr(self, 'writeBtn%d' % n).clicked.connect(do_write)

    def on_pollData(self, attrs):
        for n in range(1, 5):
            if self._polled[n - 1]:
                txt = getattr(self, 'comEdit%d' % n).text()
                inp = from_input_string(CmdArgType.DevString, txt)
                try:
                    outp = self.proxy.Communicate(inp)
                    res = to_presentation_inline(CmdArgType.DevString, outp)
                except Exception as err:
                    res = repr(err)
                getattr(self, 'comRes%d' % n).setText(res)


class DigitalInput(Base):  # also DiscreteInput
    UIFILE = 'mlz_digitalinput.ui'
    POLL_ATTRS = ['value']

    def on_pollData(self, attrs):
        val = attrs['value'].value
        self.valueLbl.setText(str(val))
        self.baseValueLbl.setText('%s | %s' % (hex(val), bin(val)))


class DigitalOutput(Base):
    UIFILE = 'mlz_digitaloutput.ui'
    POLL_ATTRS = ['value']

    def reinit(self):
        self._bits = int(self.props['bits'])
        self._maxv = (1 << self._bits) - 1
        self.minLbl.setText('0')
        self.maxLbl.setText(str(self._maxv))
        self.valueSlider.setRange(0, self._maxv)
        val = self.proxy.read_attribute('value')
        self._last_tgt = val.w_value
        if self._last_tgt is not None:
            self.targetBox.setText(str(self._last_tgt))
        else:
            self.targetBox.setText(str(val.value))

    def on_pollData(self, attrs):
        val = attrs['value'].value
        self.valueLbl.setText(str(val))
        self.baseValueLbl.setText('%s | %s' % (hex(val), bin(val)))
        if not self.valueSlider.isSliderDown():
            val = clamp(val, self.valueSlider.minimum(),
                        self.valueSlider.maximum())
            self.valueSlider.setValue(val)
        tgt = attrs['value'].w_value
        if tgt != self._last_tgt and tgt is not None:
            self._last_tgt = tgt
            self.targetBox.setText(str(tgt))

    @pyqtSlot()
    def on_moveBtn_clicked(self):
        self._write_attr('value', loud_int(self.targetBox.text()))

    def on_targetBox_returnPressed(self):
        self.on_moveBtn_clicked()
        self.targetBox.selectAll()

    def on_valueSlider_sliderMoved(self, _):
        self.targetBox.setText(str(self.valueSlider.sliderPosition()))

    def on_valueSlider_sliderReleased(self):
        self.targetBox.setText(str(self.valueSlider.value()))


class DiscreteOutput(DigitalOutput):
    UIFILE = 'mlz_discreteoutput.ui'
    POLL_ATTRS = ['value']

    def reinit(self):
        self.minLbl.setText(self.props['absmin'])
        self.maxLbl.setText(self.props['absmax'])
        self.valueSlider.setRange(int(self.props['absmin']),
                                  int(self.props['absmax']))
        val = self.proxy.read_attribute('value')
        self._last_tgt = val.w_value
        if self._last_tgt is not None:
            self.targetBox.setText(str(self._last_tgt))
        else:
            self.targetBox.setText(str(val.value))

    @pyqtSlot()
    def on_stopBtn_clicked(self):
        self._execute('Stop')


class AnalogInput(Base):
    UIFILE = 'mlz_analoginput.ui'
    POLL_ATTRS = ['value']

    def reinit(self):
        unit = self.proxy.attribute_query('value').unit
        self.unitLbl.setText(unit)

    def on_pollData(self, attrs):
        self.valueLbl.setText(str(attrs['value'].value))


class Sensor(AnalogInput):
    UIFILE = 'mlz_sensor.ui'
    POLL_ATTRS = ['value', 'rawValue']

    def on_pollData(self, attrs):
        AnalogInput.on_pollData(self, attrs)
        self.rawvalLbl.setText(str(attrs['rawValue'].value))

    @pyqtSlot()
    def on_adjustBtn_clicked(self):
        value, ok = QInputDialog.getText(self, 'Adjust device',
                                         'Enter the new value:',
                                         text=str(self.proxy.value))
        if ok:
            self._execute('Adjust', loud_float(value))


class AnalogOutput(Base):
    UIFILE = 'mlz_analogoutput.ui'
    POLL_ATTRS = ['value']

    def reinit(self):
        self.minLbl.setText(self.props['absmin'])
        self.maxLbl.setText(self.props['absmax'])
        self._offset = float(self.props['absmin'])
        srange = float(self.valueSlider.maximum())
        self._slope = (float(self.props['absmax']) -
                       float(self.props['absmin'])) / srange

        unit = self.proxy.attribute_query('value').unit
        self.unitLbl.setText(unit)
        val = self.proxy.read_attribute('value')
        self._last_tgt = val.w_value
        if self._last_tgt is not None:
            self.targetBox.setText(str(self._last_tgt))
        else:
            self.targetBox.setText(str(val.value))

    def _toslider(self, val):
        if self._slope:
            return (val - self._offset) / self._slope
        return 0

    def _fromslider(self, val):
        return (val * self._slope) + self._offset

    def on_pollData(self, attrs):
        self.valueLbl.setText(str(attrs['value'].value))
        if not self.valueSlider.isSliderDown():
            val = self._toslider(attrs['value'].value)
            # NOTE: QSlider.setValue claims to clamp itself, but crashes
            # on very large values.
            val = clamp(val, self.valueSlider.minimum(),
                        self.valueSlider.maximum())
            self.valueSlider.setValue(val)
        tgt = attrs['value'].w_value
        if tgt != self._last_tgt and tgt is not None:
            self._last_tgt = tgt
            self.targetBox.setText(str(tgt))

    @pyqtSlot()
    def on_moveBtn_clicked(self):
        self._write_attr('value', loud_float(self.targetBox.text()))

    @pyqtSlot()
    def on_stopBtn_clicked(self):
        self._execute('Stop')

    def on_targetBox_returnPressed(self):
        self.on_moveBtn_clicked()
        self.targetBox.selectAll()

    def on_valueSlider_sliderMoved(self, _):
        target = self._fromslider(self.valueSlider.sliderPosition())
        self.targetBox.setText(str(target))

    def on_valueSlider_sliderReleased(self):
        target = self._fromslider(self.valueSlider.value())
        self.targetBox.setText(str(target))


class Actuator(AnalogOutput):
    UIFILE = 'mlz_actuator.ui'
    POLL_ATTRS = ['value', 'rawValue']

    def reinit(self):
        AnalogOutput.reinit(self)
        self.speedBox.setText(str(self.proxy.speed))

    def on_pollData(self, attrs):
        AnalogOutput.on_pollData(self, attrs)
        self.rawvalLbl.setText(str(attrs['rawValue'].value))

    @pyqtSlot()
    def on_speedBtn_clicked(self):
        self._write_attr('speed', loud_float(self.speedBox.text()))
        self.speedBox.setText(str(self.proxy.speed))

    @pyqtSlot()
    def on_adjustBtn_clicked(self):
        value, ok = QInputDialog.getText(self, 'Adjust device',
                                         'Enter the new value:',
                                         text=str(self.proxy.value))
        if ok:
            self._execute('Adjust', loud_float(value))

    @pyqtSlot()
    def on_speedRereadBtn_clicked(self):
        self.speedBox.setText(str(self.proxy.speed))


class Motor(Actuator):
    UIFILE = 'mlz_motor.ui'

    def reinit(self):
        Actuator.reinit(self)
        self.accelBox.setText(str(self.proxy.accel))
        self.decelBox.setText(str(self.proxy.decel))
        self.contSpeedBox.setText(str(self.proxy.speed))

    @pyqtSlot()
    def on_contLeftBtn_clicked(self):
        spd = loud_float(self.contSpeedBox.text())
        self._execute('MoveCont', -spd)

    @pyqtSlot()
    def on_contRightBtn_clicked(self):
        spd = loud_float(self.contSpeedBox.text())
        self._execute('MoveCont', spd)

    @pyqtSlot()
    def on_accelBtn_clicked(self):
        self._write_attr('accel', loud_float(self.accelBox.text()))
        self.accelBox.setText(str(self.proxy.accel))

    @pyqtSlot()
    def on_decelBtn_clicked(self):
        self._write_attr('decel', loud_float(self.decelBox.text()))
        self.decelBox.setText(str(self.proxy.decel))

    @pyqtSlot()
    def on_refBtn_clicked(self):
        self._execute('Reference')

    @pyqtSlot()
    def on_accelRereadBtn_clicked(self):
        self.accelBox.setText(str(self.proxy.accel))

    @pyqtSlot()
    def on_decelRereadBtn_clicked(self):
        self.decelBox.setText(str(self.proxy.decel))


class Polygon():
    def __init__(self):
        self.outer=list()
    def readWKT(self,str):
        try:
            stp = "POLYGON"
            rings=str.find(stp)
            oi=str[rings+len(stp):]
            mo1 = re.search('\(([^()]*)\)',oi)  # first object only which is outer ring
            strouter =oi[mo1.regs[1][0]:mo1.regs[1][1]]
            strpts = strouter.split(',')
            tmpouter=list()
            for strpt in strpts:
                 strxy=strpt.split(' ')
                 p = QPoint(int(strxy[0]),int(strxy[1]))
                 tmpouter.append(p)
            self.outer=tmpouter
        except :
            print("Error reading Polygon from:"+str)

        
    def WKT(self):
        wkt="POLYGON(("
        for xy in self.outer:
               wkt+=str(xy.x())
               wkt+=" "
               wkt+=str(xy.y())
               wkt+=","
        wkt=wkt[:-1] # we strip the "," at the end
        wkt+="),())"
        return wkt

    def addPoint(self,val):
        self.outer.append(val)
        
    def close(self):
        n=len(self.outer)
        if n>=3:
            last = self.outer[n-1]
            if not (last.x() is self.outer[0].x() and last.y() is self.outer[0].y()):
                self.outer.append(self.outer[0])

    def vertices(self):
        return self.outer

class HistogramChannel(Base):  # also DiscreteInput
    UIFILE = 'mlz_histogramChannel.ui'
    POLL_ATTRS = ['value']

    def reinit(self):
        self.zoom = self.bZoom.isChecked()
        self.poly=Polygon()
        self.ineditroi=False
        self.wktIsRed=False
        self.editRoiBtn.clicked.connect(self.on_editRoiBtn_clicked)
        self.wktText.textChanged.connect(self.on_wktText_textchanged)
        self.on_readWKT_clicked()
        pass
    @pyqtSlot()
    def on_editRoiBtn_clicked(self):
        self.ineditroi=True
        self.poly.vertices().clear()
    def on_wktText_textchanged(self):
        if self.wktIsRed:
            self.wktIsRed=False
            tf=QTextCharFormat()
            tf.setForeground(QBrush(Qt.black))
            txt=self.wktText.toPlainText() 
            self.wktText.setCurrentCharFormat(tf)
            self.wktText.setPlainText(txt)
            self.wktText.update()
    def on_pollData(self, attrs):
        val = attrs['value'].value
        shape=self.proxy.detectorSize
        self.mat = val.reshape(shape)
        max=np.amax(val)
        if max == 0:
            max=1
        img = (self.mat*(255/max)).astype(np.uint8)
        img=cv.applyColorMap(img,cv.COLORMAP_JET)
        self.image = img      
        self.image = QImage(self.image.data, self.image.shape[0], self.image.shape[1],QImage.Format_RGB888).rgbSwapped()
        self.cts.setText(str(self.proxy.CountsInRoi))
        self.image_frame.repaint()
    @pyqtSlot()
    def on_writeWKT_clicked(self):
        wkt=str(self.wktText.toPlainText())
        self.proxy.setRoiWKT(wkt) 
        self.on_readWKT_clicked()
    @pyqtSlot()
    def on_readWKT_clicked(self):
        tf=QTextCharFormat()
        tf.setForeground(QBrush(Qt.red))
        self.wktText.setCurrentCharFormat(tf)
        self.wktText.setPlainText(self.proxy.RoiWKT) 
        self.poly.readWKT(self.wktText.toPlainText())
        self.wktIsRed=True
        self.wktText.update()
    @pyqtSlot()
    def on_saveBtn_clicked(self):
        filename=QFileDialog.getSaveFileName(self,"Save Histogramm","histogram.csv","Text (*.csv)")
        #filename ='C:\\Users\\Andreas\\a.xml'
        np.savetxt(filename[0], self.mat, delimiter=',') 
        
    def paintEvent(self, event):
        #self.image = cv.imread('c:\\temp\\testa.PNG')
        #pixmap = QPixmap.fromImage(self.image)
        img = self.image
        self.zoom = self.bZoom.isChecked()
        if self.zoom:
              img = self.image.scaledToWidth(self.image.width()*2)
        painter = QPainter()
        painter.begin(self)
        
        painter.drawImage(self.image_frame.x(),self.image_frame.y(),img)
        pen = QPen(Qt.red, 2)
        painter.setPen(pen)
        lastdp=None
        for qp in self.poly.vertices():
            qpz=copy.copy(qp)
            if self.zoom:  
                qpz.setX(qpz.x()*2)
                qpz.setY(qpz.y()*2)
           
            adp=self.image_frame.mapToParent(qpz)
            if not (lastdp is None):
                 painter.drawLine(lastdp,adp)
                 
            lastdp=adp
        painter.end()
    def keyPressEvent(self,event):
        if event.key() == Qt.Key_Escape:
            self.ineditroi=False
    def mousePressEvent(self, event):
        if self.ineditroi:
            if event.button() == Qt.LeftButton:
                mpos=self.image_frame.mapFromParent(event.pos())
                zf=1
                if self.zoom :
                    mpos/=2
                    zf=2

                doprint = True
                if not (mpos.x() >=0 and mpos.x() <= self.image.width()*zf): doprint=False
                if not (mpos.y() >=0 and mpos.y() <= self.image.size().height()*zf): doprint=False
                if doprint:
                    self.poly.addPoint(mpos)
                    self.update()

            if event.button() == Qt.RightButton:
                    self.poly.close()
                    self.ineditroi=False
                    wkt = self.poly.WKT()
                    self.wktText.setPlainText(wkt)
                    self.update()
                    

BASE_CMDS = ['GetProperties', 'Off', 'On', 'Reset']
ACTUATOR_CMDS = BASE_CMDS + ['Adjust', 'Stop']

INTERFACES = [
    (StringIO, BASE_CMDS + ['Communicate', 'WriteLine'], [], None),
    (HistogramChannel, BASE_CMDS, ['RoiWKT','value'], 'int-ro'),
    (Motor, ACTUATOR_CMDS + ['Reference', 'MoveCont'],
     ['value', 'rawValue', 'speed', 'accel', 'decel'], 'float-rw'),
    (Actuator, ACTUATOR_CMDS, ['value', 'rawValue', 'speed'], 'float-rw'),
    (AnalogOutput, BASE_CMDS + ['Stop'], ['value'], 'float-rw'),
    (DiscreteOutput, BASE_CMDS + ['Stop'], ['value'], 'int-rw'),
    (DigitalOutput, BASE_CMDS, ['value'], 'int-rw'),
    (Sensor, BASE_CMDS, ['value', 'rawValue'], 'float-ro'),
    (AnalogInput, BASE_CMDS, ['value'], 'float-ro'),
    (DigitalInput, BASE_CMDS, ['value'], 'int-ro')
  
]
