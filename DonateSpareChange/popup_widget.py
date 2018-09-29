#
# PopupWidget and PopupLabel
# by Calin Culianu <calin.culianu@gmail.com>
#
# Adapted from my C++ sourcecode used in the VikingRecorder project.
#
# LICENSE: MIT
#
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

LR_MARGIN = 8.0 #/* left / right margin  */
TB_MARGIN = 5.5 #/* top / bottom margin */


class PopupWidget(QWidget):

    #   enum PointerPosition
    LeftSide = 0; RightSide = 1;  TopSide = 2; BottomSide = 3; NoPointer = 4


    def __init__(self, parent = None):
        super().__init__(parent)
        self.layout = QGridLayout(self)
        self.animation = QPropertyAnimation()
        self._finalOpacity = 1.0
        self._popupOpacity = 1.0
        self.pointerPos = self.LeftSide

        self.resize(200, 50)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.animation.setTargetObject(self)
        self.animation.setPropertyName(b'popupOpacity')
        self.animation.setDuration(200)

        self.setLayout(self.layout)

    def getPointerPosition(self): return self.pointerPos
    def setPointerPosition(self, r): self.pointerPos = r; self.update()

    @pyqtProperty(float)
    def popupOpacity(self): return self._popupOpacity
    @popupOpacity.setter
    def popupOpacity(self, value):
        self._popupOpacity = value
        self.setWindowOpacity(value)
    @pyqtProperty(float)
    def finalOpacity(self): return self._finalOpacity
    @finalOpacity.setter
    def finalOpacity(self, value): self._finalOpacity = value

    def paintEvent(self, e):
        #// Draw the popup here
        #// You can always pick an image and use drawPixmap to
        #// draw it in order to make things simpler

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRegion(e.region())
        painter.fillRect(e.rect(),QColor(0,0,0,0))

        #// Prepare the popup dimensions
        roundedRectDimensions = QRectF()
        roundedRectDimensions.setX(self.rect().x() + LR_MARGIN)
        roundedRectDimensions.setY(self.rect().y() + TB_MARGIN)
        roundedRectDimensions.setWidth(self.rect().width() - LR_MARGIN*2.0)
        roundedRectDimensions.setHeight(self.rect().height() - TB_MARGIN*2.0)

        pal = QPalette(self.palette())

        painter.setBrush(QBrush(pal.color(QPalette.Mid)))


        pen = QPen()
        pen.setColor(pal.color(QPalette.Button))
        pen.setWidth(3)
        painter.setPen(pen)

        #// Draw the popup body
        painter.drawRoundedRect(roundedRectDimensions, LR_MARGIN*2.0, TB_MARGIN*2.0)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(pal.color(QPalette.Dark)))
        #// Draw the popup pointer based on relPos
        self.drawPopupPointer(painter)

        e.accept()

    def drawPopupPointer(self, p):
        r = QRectF(self.rect())

        if self.pointerPos == self.LeftSide:
            PPIX_X = LR_MARGIN; PPIX_Y = PPIX_X*2.0
            points = [
                QPointF(QPoint(r.x()+PPIX_X, r.height()/2.0 - PPIX_Y/2.0)),
                QPointF(QPoint(r.x()+PPIX_X, r.height()/2.0 + PPIX_Y/2.0)),
                QPointF(QPoint(r.x(), r.height() / 2.0))
            ]

            p.drawPolygon(*points)

        if self.pointerPos == self.RightSide:
            PPIX_X = LR_MARGIN; PPIX_Y = PPIX_X*2.0
            points = [
                QPointF(QPoint(r.right()-PPIX_X, r.height()/2.0 - PPIX_Y/2.0)),
                QPointF(QPoint(r.right()-PPIX_X, r.height()/2.0 + PPIX_Y/2.0)),
                QPointF(QPoint(r.right(), r.height() / 2.0))
            ]

            p.drawPolygon(*points)

        if self.pointerPos == self.TopSide:
            PPIX_Y = TB_MARGIN; PPIX_X = PPIX_Y*2.0
            points = [
                QPointF(QPoint(r.x()+r.width()/2.0 - PPIX_X/2.0, r.top() + PPIX_Y)),
                QPointF(QPoint(r.x()+r.width()/2.0 + PPIX_X/2.0, r.top() + PPIX_Y)),
                QPointF(QPoint(r.x()+r.width()/2.0, r.top()))
            ]

            p.drawPolygon(*points)

        if self.pointerPos == self.BottomSide:
            PPIX_Y = TB_MARGIN; PPIX_X = PPIX_Y*2.0
            points = [
                QPointF(QPoint(r.x()+r.width()/2.0 - PPIX_X/2.0, r.bottom() - PPIX_Y)),
                QPointF(QPoint(r.x()+r.width()/2.0 + PPIX_X/2.0, r.bottom() - PPIX_Y)),
                QPointF(QPoint(r.x()+r.width()/2.0, r.bottom()))
            ]

            p.drawPolygon(*points)

    def showRelativeTo(self, w):
        self.moveRelativeTo(w)
        self.hide()
        self.show()
        if self.pointerPos == self.NoPointer:
            self.raise_()

    def moveRelativeTo(self, w):
        if not w:
            print("INTERNAL ERROR: PopupWidget::showRelativeTo got passed a NULL widget pointer! Ignoring.. FIXME!")
            return

        p = w.parentWidget().mapToGlobal(w.pos()) if w.parentWidget() else w.pos()
        if self.pointerPos == self.LeftSide:
            p.setX(p.x()+w.width())
            p.setY(p.y()-self.height()/2+w.height()/2)
        elif self.pointerPos == self.RightSide:
            p.setX(p.x()-self.width())
            p.setY(p.y()-self.height()/2+w.height()/2)
        elif self.pointerPos == self.BottomSide:
            p.setX(p.x()+w.width()/2 - self.width()/2)
            p.setY(p.y()-self.height())
        elif self.pointerPos == self.TopSide:
            p.setX(p.x()+w.width()/2 - self.width()/2)
            p.setY(p.y()+w.height())
        else:
            #// just center it on the widget
            p.setX(p.x()+w.width()/2 - self.width()/2)
            p.setY(p.y()+w.height()/2 - self.height()/2)
            if self.isVisible():
                self.raise_()

        self.move(p);


    def show(self):
        self.setWindowOpacity(0.0)

        self.animation.setStartValue(0.0)
        self.animation.setEndValue(self._finalOpacity)

        super().show()

        self.animation.start()


class PopupLabel(PopupWidget):

    def __init__(self, text = "", parent = None):
        super().__init__(parent)
        self.label = QLabel(text, self)
        self.label.setAlignment(Qt.AlignVCenter|Qt.AlignJustify)
        self.label.setWordWrap(True)
        self.label.setScaledContents(True)
        p = QPalette(self.label.palette())
        p.setColor(QPalette.Window,QColor(0,0,0,0))
        self.label.setPalette(p);

        self.layout.addWidget(self.label, 0, 0);

        self.setAutoFillBackground(False)
        self.setUpdatesEnabled(True)

    def setPopupText(self, text):
        self.label.setText(text)
